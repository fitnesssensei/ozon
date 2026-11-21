#!/usr/bin/env python3
"""Скачивание всех фото галерей товаров магазина Ozon (магазин — в shop_config.py).

Структура результата:
    shops/<магазин>/
      README.md
      index.json          # машинный индекс: книга -> папка -> файлы + исходные URL
      index.csv           # тот же индекс для Excel/просмотра глазами
      _errors.jsonl       # ошибки по книгам (можно перезапускать)
      zdorove-muzhchiny-tom-3/
        info.json         # sku, name, url, price, photos[{file, src}]
        01.jpg
        02.jpg

Транспорт (проверено 18.11.2026):
  - каталог и карточки: playwright BrowserContext.request
    (requests/httpx с теми же cookie получают 403 fab_*);
  - картинки: requests напрямую с https://ir.ozone.ru (публичный CDN, без авторизации).

Идемпотентно: повторный запуск пропускает готовые книги и уже скачанные файлы.
"""
import argparse
import asyncio
import csv
import json
import pathlib
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import requests
from playwright.async_api import async_playwright

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from poc_ozon_prices import (API, STATE, UA, ensure_adult, ensure_state,  # noqa: E402
                             to_decimal)
from shop_config import (BASE_URL, CATALOG_PAGE_PATH, IMAGES_DIR, SELLER_ID,  # noqa: E402
                         SLUG, TITLE)

ROOT = IMAGES_DIR
IMG_TIMEOUT = 90


# ------------------------------------------------------------------ parsing
def parse_catalog_items(payload: dict) -> list[dict]:
    """Товары из виджета каталога магазина (8 штук на страницу)."""
    grid = None
    for key, raw in (payload.get("widgetStates") or {}).items():
        if not key.startswith("tileGridDesktop"):
            continue
        g = json.loads(raw)
        items = g.get("items") or []
        if items and "brandLogo" in items[0] and g.get("header") is None:
            grid = g
            break
    if grid is None:
        return []

    out = []
    for tile in grid["items"]:
        pv = next((b["priceV2"] for b in tile.get("mainState", [])
                   if b.get("type") == "priceV2"), {})
        texts = {p["textStyle"]: p["text"] for p in pv.get("price", [])}
        name = next((b["textDS"]["text"] for b in tile.get("mainState", [])
                     if b.get("type") == "textDS"
                     and b["textDS"].get("testInfo", {}).get("automatizationId") == "tile-name"), None)
        link = (tile.get("action") or {}).get("link", "")
        cover = None
        for item in (tile.get("tileImage") or {}).get("items", []):
            cover = (item.get("image") or {}).get("link") or cover
            if cover:
                break
        out.append({
            "sku": str(tile["sku"]),
            "url": BASE_URL + link.split("?")[0],
            "name": name,
            "price": str(to_decimal(texts.get("PRICE")) or ""),
            "price_style": (pv.get("priceStyle") or {}).get("styleType"),
            "cover": cover,
        })
    return out


def parse_gallery(payload: dict) -> list[str]:
    """Фото из webGallery; если галереи нет/пуста — fallback на coverImage."""
    for key, raw in (payload.get("widgetStates") or {}).items():
        if not key.startswith("webGallery"):
            continue
        g = json.loads(raw)
        srcs = [i.get("src") for i in (g.get("images") or []) if i.get("src")]
        if not srcs and g.get("coverImage"):
            srcs = [g["coverImage"]]
        return list(dict.fromkeys(srcs))
    return []


def _widget(ws: dict, prefix: str) -> dict:
    for key, raw in ws.items():
        if key.startswith(prefix):
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return {}
    return {}


def _texts(obj, depth: int = 0) -> list[str]:
    """Все строки из поля text/content в структуре (для «мягкого» разбора)."""
    out: list[str] = []
    if depth > 7:
        return out
    if isinstance(obj, dict):
        for key, val in obj.items():
            if key in ("text", "content") and isinstance(val, str) and val.strip():
                out.append(val.strip())
            else:
                out.extend(_texts(val, depth + 1))
    elif isinstance(obj, list):
        for val in obj:
            out.extend(_texts(val, depth + 1))
    return out


def parse_description(payload: dict) -> str | None:
    """Самое длинное описание из виджетов `webDescription`/`webAnnotation`.

    Ozon в `shortDescription` отдаёт обрезанный текст (~200 символов).
    Полный текст, если он есть, лежит в других ключах виджета (`text`,
    `richAnnotation`, `fullDescription` и т.п.), поэтому собираем всех
    кандидатов и берём самый длинный.
    """
    ws = payload.get("widgetStates") or {}
    candidates: list[str] = []

    def walk(obj, depth: int = 0) -> None:
        if depth > 8:
            return
        if isinstance(obj, dict):
            for key, value in obj.items():
                if isinstance(value, str):
                    name = key.lower()
                    if name in {
                        "shortdescription", "description", "fulldescription",
                        "text", "content", "annotation", "richannotation",
                    } and value.strip():
                        candidates.append(value.strip())
                elif isinstance(value, (dict, list)):
                    walk(value, depth + 1)
        elif isinstance(obj, list):
            for value in obj:
                walk(value, depth + 1)

    for key, raw in ws.items():
        name = key.lower()
        if "description" not in name and "annotation" not in name:
            continue
        try:
            walk(json.loads(raw))
        except json.JSONDecodeError:
            continue

    if not candidates:
        return None
    # Убираем повторы, сохраняя порядок, и берём самый длинный текст.
    unique = list(dict.fromkeys(candidates))
    return max(unique, key=len)


def _num(text: str | None) -> float | None:
    if not text:
        return None
    m = re.search(r"\d+(?:[.,]\d+)?", text.replace("\u2009", ""))
    return float(m.group(0).replace(",", ".")) if m else None


def parse_card(payload: dict) -> dict:
    """Расширенные данные книги из первого фрагмента карточки (0 доп. запросов)."""
    ws = payload.get("widgetStates") or {}
    head = _widget(ws, "webProductHeading")
    price = _widget(ws, "webPrice")
    seller = _widget(ws, "webCurrentSeller")
    score = _widget(ws, "webReviewProductScore")
    single = _widget(ws, "webSingleProductScore")
    labels = _widget(ws, "webMarketingLabels").get("labels") or []
    crumbs = _widget(ws, "breadCrumbs").get("breadcrumbs") or []
    detail = _widget(ws, "webDetailSKU")

    title = head.get("title")
    name = title if isinstance(title, str) else (title or {}).get("text")

    seller_name = (((seller.get("sellerCell") or {}).get("centerBlock") or {})
                   .get("title") or {}).get("text")
    seller_rating = (((seller.get("rating") or {}).get("title") or {}).get("text"))
    seller_dump = json.dumps(seller, ensure_ascii=False)
    followers = re.search(r"(\d+)\s*подписчик", seller_dump)
    seller_path = re.search(r'"(/seller/[^"?]{2,60})', seller_dump)

    score_dump = json.dumps(score, ensure_ascii=False) + " " + json.dumps(single, ensure_ascii=False)
    reviews = re.search(r"(\d+)\s*отзыв", score_dump)
    single_text = (single.get("text") or "").strip()
    rating = _num(single_text) if single_text and not single_text.lower().startswith("нет") else None

    return {
        "name": name,
        "description": parse_description(payload),
        "price_card": str(to_decimal(price.get("cardPrice"))) if price.get("cardPrice") else None,
        "price_regular": str(to_decimal(price.get("price"))) if price.get("price") else None,
        "available": price.get("isAvailable"),
        "rating": rating,
        "reviews_count": int(reviews.group(1)) if reviews else None,
        "seller": {
            "id": SELLER_ID,
            "name": seller_name,
            "rating": _num(seller_rating) if seller_rating else None,
            "followers": int(followers.group(1)) if followers else None,
            "url": (BASE_URL + seller_path.group(1)) if seller_path else None,
        },
        "category": [c.get("text") for c in crumbs if c.get("text")],
        "labels": [x.get("text") for x in labels if x.get("text")],
        "article": detail.get("copyText"),
        "short_characteristics": parse_short_chars(payload),
    }


def parse_short_chars(payload: dict) -> dict:
    """Краткие характеристики из первого фрагмента (Автор, Серия, Год…) — fallback."""
    w = _widget(payload.get("widgetStates") or {}, "webShortCharacteristics")
    out: dict[str, list[str]] = {}
    for item in w.get("characteristics") or []:
        title = " ".join(str(t.get("content") or t.get("text") or "")
                         for t in (item.get("title") or {}).get("textRs", [])).strip()
        vals = [v.get("text") for v in item.get("values") or [] if v.get("text")]
        if title and vals:
            out.setdefault(title, vals)
    return out


def parse_chars(payload: dict) -> dict:
    """Все характеристики из второго фрагмента карточки (webCharacteristics)."""
    out: dict[str, list[str]] = {}
    for key, raw in (payload.get("widgetStates") or {}).items():
        if not key.startswith("webCharacteristics"):
            continue
        w = json.loads(raw)
        for group in w.get("characteristics") or []:
            for item in (group.get("short") or []) + (group.get("full") or []):
                name = item.get("name")
                vals = [v.get("text") for v in item.get("values") or [] if v.get("text")]
                if name and vals:
                    out[name] = vals
    return out


def folder_name(sku: str, url: str) -> str:
    """Короткий slug без SKU: папка должна совпадать с уже переименованными."""
    slug = url.rstrip("/").rsplit("/", 1)[-1]
    slug = re.sub(r"-\d+$", "", slug)
    slug = re.sub(r"[^a-z0-9-]+", "-", slug.lower()).strip("-")
    slug = slug[:45].strip("-")
    return slug or sku


def unique_folder_name(root: pathlib.Path, sku: str, url: str,
                       used: set[str] | None = None) -> str:
    """Свободное имя папки; при совпадении — `1_...`, `2_...` и далее."""
    base = folder_name(sku, url)
    used = used if used is not None else set()
    if base not in used and not (root / base).exists():
        return base
    number = 1
    while True:
        candidate = f"{number}_{base}"
        if candidate not in used and not (root / candidate).exists():
            return candidate
        number += 1


def ext_of(url: str) -> str:
    m = re.search(r"\.(jpe?g|png|webp)(?:\?|$)", url.lower())
    return "." + (m.group(1).replace("jpeg", "jpg") if m else "jpg")


# ------------------------------------------------------------------ download
def download_one(src: str, dest: pathlib.Path) -> tuple[str, int, str | None]:
    """Скачать один файл; вернуть (src, размер, ошибка)."""
    try:
        if dest.exists() and dest.stat().st_size > 1024:
            return src, dest.stat().st_size, None
        tmp = dest.with_name(dest.name + ".part")
        with requests.get(src, headers={"User-Agent": UA, "Referer": "https://www.ozon.ru/"},
                          timeout=IMG_TIMEOUT, stream=True) as r:
            r.raise_for_status()
            ctype = r.headers.get("content-type", "")
            if "image" not in ctype:
                return src, 0, f"content-type={ctype}"
            size = 0
            with tmp.open("wb") as fh:
                for chunk in r.iter_content(65536):
                    fh.write(chunk)
                    size += len(chunk)
        if size < 1024:
            tmp.unlink(missing_ok=True)
            return src, 0, f"too small: {size} bytes"
        tmp.rename(dest)
        return src, size, None
    except Exception as exc:  # noqa: BLE001 - нужен текст любой ошибки
        return src, 0, f"{type(exc).__name__}: {exc}"


def scan_books(root: pathlib.Path) -> list[dict]:
    """Все книги, у которых на диске есть info.json."""
    books = []
    for folder in sorted(p for p in root.iterdir() if p.is_dir()):
        info = load_cached_info(folder / "info.json")
        if info:
            books.append(index_entry(info))
    return books


def rebuild_from_disk(root: pathlib.Path) -> list[dict]:
    books = scan_books(root)
    dump_index(root, books)
    return books


def write_readme(root: pathlib.Path) -> None:
    (root / "README.md").write_text(
        f"# Фото товаров магазина «{TITLE}» (Ozon)\n\n"
        "Одна папка = один товар: `<короткий-slug>`; при совпадении имён — `1_<slug>`, `2_<slug>`.\n\n"
        "- `NN.jpg` — фото галереи карточки в исходном порядке (обложка первая);\n"
        "- `info.json` — `sku`, `name`, `url`, `price`, `price_style`, `photos[{file, src}]`;\n"
        "- `index.json` / `index.csv` — сводный индекс всех книг (для сайта/Excel);\n"
        "- `_errors.jsonl` — что не скачалось (перезапуск докачает).\n\n"
        "Как показывать на сайте: брать `index.json` → `books[].folder` + `photos[].file`\n"
        "и отдавать файлы со своего домена (или `photos[].src` — исходный CDN Ozon).\n\n"
        "Правовая оговорка: изображения принадлежат правообладателям; публичное\n"
        "использование — на ответственности того, кто публикует.\n",
        encoding="utf-8",
    )


def dump_index(root: pathlib.Path, books: list[dict]) -> None:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    total_photos = sum(len(b.get("photos") or []) for b in books)
    payload = {"generated_at": now, "seller": SLUG, "books_count": len(books),
               "photos_count": total_photos, "books": books}
    tmp = root / "index.json.tmp"
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.rename(root / "index.json")

    with (root / "index.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["sku", "name", "price", "price_style", "available", "rating", "reviews",
                    "chars_count", "seller", "photos_count", "folder", "url"])
        for b in books:
            w.writerow([b["sku"], b.get("name") or "", b.get("price") or "",
                        b.get("price_style") or "", b.get("available"),
                        b.get("rating"), b.get("reviews_count"), b.get("chars_count"),
                        b.get("seller") or "", len(b.get("photos") or []),
                        b["folder"], b.get("url") or ""])


async def fetch_catalog(ctx, limit_books: int, delay: float, cache: pathlib.Path,
                        refresh: bool = False) -> list[dict]:
    """Список книг из каталога; кешируется в images/_books.json, чтобы не перечитывать 109 страниц."""
    if cache.exists() and not refresh:
        books = json.loads(cache.read_text(encoding="utf-8"))
        seen: set[str] = set()
        books = [b for b in books if not (b["sku"] in seen or seen.add(b["sku"]))]
        print(f"[catalog] из кеша: {len(books)} книг ({cache.name})", flush=True)
        return books[:limit_books] if limit_books else books
    books, page = [], 1
    while True:
        r = await ctx.request.get(API, params={"url": CATALOG_PAGE_PATH.format(page=page)},
                                  timeout=40000)
        if r.status != 200:
            raise RuntimeError(f"catalog page {page}: HTTP {r.status}")
        items = parse_catalog_items(json.loads(await r.body()))
        if not items:
            break
        books.extend(items)
        print(f"[catalog] page {page}: +{len(items)}, всего {len(books)}", flush=True)
        if limit_books and len(books) >= limit_books:
            books = books[:limit_books]
            break
        page += 1
        await asyncio.sleep(delay)
    if not limit_books:
        seen: set[str] = set()
        uniq = []
        for b in books:
            if b["sku"] in seen:
                continue
            seen.add(b["sku"])
            uniq.append(b)
        if len(uniq) != len(books):
            print(f"[catalog] дубли SKU убраны: {len(books)} -> {len(uniq)}", flush=True)
        books = uniq
        cache.write_text(json.dumps(books, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"[catalog] список сохранён: {cache.name} ({len(books)} книг)", flush=True)
    return books


def load_cached_info(path: pathlib.Path) -> dict | None:
    if not path.exists():
        return None
    try:
        info = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return info if "photos" in info else None


def index_entry(info: dict) -> dict:
    chars = info.get("characteristics") or {}
    seller = info.get("seller") or {}
    return {"folder": info["folder"], "sku": info["sku"], "name": info.get("name"),
            "url": info.get("url"), "price": info.get("price"),
            "price_style": info.get("price_style"), "available": info.get("available"),
            "rating": info.get("rating"), "reviews_count": info.get("reviews_count"),
            "seller": seller.get("name"), "chars_count": len(chars),
            "photos": info.get("photos") or []}


async def fetch_card_info(ctx, book: dict, n: int, total: int, with_chars: bool = True):
    """Возвращает (фото, данные карточки, характеристики).

    Первый фрагмент — галерея, цена, рейтинг, продавец, категория, описание.
    Второй (layout_container=pdpPage2column&layout_page_index=2) — все характеристики.
    """
    path = book["url"].replace(BASE_URL, "")
    payload = None
    for attempt in (1, 2, 3):
        r = await ctx.request.get(API, params={"url": path}, timeout=40000)
        if r.status == 200:
            payload = json.loads(await r.body())
            break
        print(f"[{n}/{total}] {book['sku']}: карточка HTTP {r.status}, попытка {attempt}/3", flush=True)
        await asyncio.sleep(10 * attempt)
    if payload is None:
        return ([book["cover"]] if book.get("cover") else []), {}, {}

    imgs = parse_gallery(payload)
    card = parse_card(payload)
    if not imgs:
        print(f"[{n}/{total}] {book['sku']}: галерея пуста → обложка из каталога", flush=True)
        imgs = [book["cover"]] if book.get("cover") else []

    chars: dict = {}
    if with_chars:
        chars_path = path + "?layout_container=pdpPage2column&layout_page_index=2"
        for attempt in (1, 2):
            r = await ctx.request.get(API, params={"url": chars_path}, timeout=40000)
            if r.status == 200:
                chars = parse_chars(json.loads(await r.body()))
                break
            await asyncio.sleep(5 * attempt)
        if not chars:
            print(f"[{n}/{total}] {book['sku']}: характеристики не пришли", flush=True)
    return imgs, card, chars


def process_book(book: dict, root: pathlib.Path, imgs: list[str], workers: int,
                 card: dict | None = None, chars: dict | None = None) -> dict:
    folder = root / book["folder"]
    folder.mkdir(parents=True, exist_ok=True)
    photos, errors = [], []
    if imgs:
        width = max(2, len(str(len(imgs))))
        tasks = [(src, folder / f"{idx:0{width}d}{ext_of(src)}") for idx, src in enumerate(imgs, 1)]
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(lambda t: download_one(t[0], t[1]), tasks))
        for (src, dest), (_s, size, err) in zip(tasks, results):
            if err:
                errors.append({"src": src, "error": err})
            else:
                photos.append({"file": dest.name, "src": src, "bytes": size})
    card = card or {}
    info = {
        "sku": book["sku"],
        "url": book.get("url"),
        "name": card.get("name") or book.get("name"),
        "folder": book["folder"],
        "price": book.get("price"),
        "price_style": book.get("price_style"),
        "price_card": card.get("price_card"),
        "price_regular": card.get("price_regular"),
        "available": card.get("available"),
        "rating": card.get("rating"),
        "reviews_count": card.get("reviews_count"),
        "seller": card.get("seller"),
        "category": card.get("category") or [],
        "labels": card.get("labels") or [],
        "article": card.get("article") or book["sku"],
        "description": card.get("description"),
        "characteristics": chars or card.get("short_characteristics") or {},
        "photos": photos,
        "downloaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    tmp = folder / "info.json.tmp"
    tmp.write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.rename(folder / "info.json")
    return {"info": info, "errors": errors}


async def run(args) -> int:
    root = pathlib.Path(args.out).resolve()
    root.mkdir(parents=True, exist_ok=True)
    write_readme(root)
    await ensure_state()

    t_start = time.time()
    books_all: list[dict] = []
    errors_path = root / "_errors.jsonl"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True,
                                          args=["--disable-blink-features=AutomationControlled"])
        ctx = await browser.new_context(user_agent=UA, locale="ru-RU", storage_state=str(STATE))
        await ensure_adult(ctx)

        books = await fetch_catalog(ctx, args.limit_books, args.delay,
                                    root / "_books.json", refresh=args.refresh_catalog)
        print(f"[catalog] итого книг: {len(books)}", flush=True)

        # Уже существующие папки переиспользуем по sku: после переименования
        # они называются без префикса, и повторный запуск не должен плодить дубли.
        existing_folders: dict[str, str] = {}
        used_names = {p.name for p in root.iterdir() if p.is_dir()}
        for folder in root.iterdir():
            if not folder.is_dir():
                continue
            info = load_cached_info(folder / "info.json")
            if info and info.get("sku"):
                existing_folders[str(info["sku"])] = folder.name

        todo: list[dict] = []
        for book in books:
            folder = existing_folders.get(book["sku"])
            if folder is None:
                folder = unique_folder_name(root, book["sku"], book["url"], used_names)
                used_names.add(folder)
            book["folder"] = folder
            cached = (load_cached_info(root / book["folder"] / "info.json")
                      if args.resume and not args.refresh_info else None)
            if cached:
                books_all.append(index_entry(cached))
            else:
                todo.append(book)
        print(f"[cards] готово ранее: {len(books_all)}, осталось: {len(todo)}, "
              f"параллельно: {args.card_concurrency}", flush=True)

        t_cards = time.time()
        processed = 0
        size = max(1, args.card_concurrency)

        async def handle(book: dict):
            imgs, card, chars = await fetch_card_info(ctx, book, len(books_all) + 1, len(books),
                                                      with_chars=args.full_chars)
            res = await asyncio.to_thread(process_book, book, root,
                                          [] if args.no_images else imgs, args.img_workers,
                                          card, chars)
            return book, res

        for start in range(0, len(todo), size):
            batch = todo[start:start + size]
            for book, res in await asyncio.gather(*(handle(b) for b in batch)):
                info, errs = res["info"], res["errors"]
                if errs:
                    with errors_path.open("a", encoding="utf-8") as fh:
                        for e in errs:
                            fh.write(json.dumps({"sku": book["sku"], **e}, ensure_ascii=False) + "\n")
                books_all.append(index_entry(info))
                processed += 1
            if processed % (size * 10) < size:
                rebuild_from_disk(root)
            elapsed = max(0.001, time.time() - t_cards)
            speed = processed / elapsed
            eta = (len(todo) - processed) / speed / 60 if speed else 0
            last = books_all[-1]
            print(f"[{len(books_all)}/{len(books)}] {last['sku']}: фото {len(last['photos'])}"
                  f" | {speed:.1f} книг/с | ETA {eta:.0f} мин", flush=True)
            await asyncio.sleep(args.delay)

        await browser.close()

    final = rebuild_from_disk(root)
    total_photos = sum(len(b["photos"]) for b in final)
    total_bytes = sum(p.get("bytes", 0) for b in final for p in b["photos"])
    print(f"\nготово: {len(final)} книг в папке, {total_photos} фото, "
          f"{total_bytes / 1024 / 1024:.0f} МБ, прогон {(time.time() - t_start) / 60:.1f} мин")
    print(f"индекс: {root / 'index.json'}\nпапка: {root}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=f"Скачивание фото галерей магазина {TITLE}")
    ap.add_argument("--out", default=str(ROOT), help="куда складывать (по умолчанию ./images)")
    ap.add_argument("--limit-books", type=int, default=0, help="0 = все книги")
    ap.add_argument("--delay", type=float, default=2.5, help="пауза между батчами карточек, сек")
    ap.add_argument("--card-concurrency", type=int, default=1,
                    help="сколько карточек обрабатывать параллельно (1 = как в плане)")
    ap.add_argument("--refresh-catalog", action="store_true",
                    help="перечитать каталог, игнорируя images/_books.json")
    ap.add_argument("--img-workers", type=int, default=3, help="параллельных скачиваний картинок")
    ap.add_argument("--no-images", action="store_true", help="только URL, без файлов")
    ap.add_argument("--no-resume", dest="resume", action="store_false", help="не пропускать готовое")
    ap.add_argument("--no-full-chars", dest="full_chars", action="store_false",
                    help="не запрашивать второй фрагмент с полными характеристиками")
    ap.add_argument("--refresh-info", action="store_true",
                    help="перезапросить карточку и характеристики для уже скачанных книг")
    args = ap.parse_args()
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
