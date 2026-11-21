#!/usr/bin/env python3
"""Шаг 0 (spike): проверка контракта каталога магазина на Ozon.

Два режима:
  --offline   разбор фикстуры + сверка с эталоном (без сети, детерминированно)
  (по умолчанию) живой прогон: bootstrap сессии -> N страниц JSON-API -> JSONL

Транспорт: playwright BrowserContext.request (Chromium network stack).
Обычный HTTP-клиент (requests/httpx) с теми же cookie получает 403 fab_*.
"""
import argparse
import asyncio
import json
import pathlib
import re
import sys
import time
from dataclasses import asdict, dataclass
from decimal import Decimal

from shop_config import (BASE_URL, CATALOG_PAGE_PATH, PRICES_FILE, PROFILE_DIR,  # noqa: E402
                         SELLER_URL, STATE_FILE)

API = "https://www.ozon.ru/api/entrypoint-api.bx/page/json/v2"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36")
HERE = pathlib.Path(__file__).resolve().parent
FIXTURES = HERE.parent / "fixtures"
STATE = STATE_FILE
PROFILE = PROFILE_DIR

# Ozon отдаёт карточки 18+ только после подтверждения возраста: вместо товара
# приходит один виджет userAdultModal. Модалка setBirthdate выставляет эти cookie —
# ставим их сами, чтобы каталог/характеристики были доступны.
ADULT_COOKIES = (
    {"name": "is_adult_confirmed", "value": "true", "domain": ".ozon.ru", "path": "/"},
    {"name": "adult_user_birthdate", "value": "1990-01-01", "domain": ".ozon.ru", "path": "/"},
)


async def ensure_adult(ctx) -> None:
    """Добавить в контекст cookie подтверждения 18+, если их ещё нет."""
    have = {c["name"]: c["value"] for c in await ctx.cookies()}
    missing = [c for c in ADULT_COOKIES if have.get(c["name"]) != c["value"]]
    if missing:
        await ctx.add_cookies(missing)


@dataclass
class ProductPrice:
    sku: str
    url: str
    name: str | None
    price: Decimal | None
    price_original: Decimal | None
    price_style: str | None
    in_stock: bool | None


class ParseError(Exception):
    pass


def to_decimal(text: str | None) -> Decimal | None:
    if not text:
        return None
    raw = (text.replace("\u2009", "").replace("\xa0", "").replace("₽", "")
           .replace(" ", "").replace(",", "."))
    m = re.search(r"\d+(?:\.\d+)?", raw)
    return Decimal(m.group(0)).quantize(Decimal("0.01")) if m else None


def catalog_grid(payload: dict) -> dict:
    """Виджет каталога магазина: tileGrid, где у плиток есть brandLogo, а header отсутствует."""
    for key, raw in (payload.get("widgetStates") or {}).items():
        if not key.startswith("tileGridDesktop"):
            continue
        grid = json.loads(raw)
        items = grid.get("items") or []
        if items and "brandLogo" in items[0] and grid.get("header") is None:
            return grid
    raise ParseError("catalog tile grid not found")


def parse_tile(tile: dict) -> ProductPrice:
    pv = next((b["priceV2"] for b in tile.get("mainState", []) if b.get("type") == "priceV2"), {})
    texts = {p["textStyle"]: p["text"] for p in pv.get("price", [])}
    name = next((b["textDS"]["text"] for b in tile.get("mainState", [])
                 if b.get("type") == "textDS"
                 and b["textDS"].get("testInfo", {}).get("automatizationId") == "tile-name"), None)
    link = (tile.get("action") or {}).get("link", "")
    if not link:
        raise ParseError(f"tile {tile.get('sku')} has no action.link")
    price = to_decimal(texts.get("PRICE"))
    return ProductPrice(
        sku=str(tile["sku"]),
        url=BASE_URL + link.split("?")[0],
        name=name,
        price=price,
        price_original=to_decimal(texts.get("ORIGINAL_PRICE")),
        price_style=(pv.get("priceStyle") or {}).get("styleType"),
        in_stock=True if price is not None else None,
    )


def parse_catalog(payload: dict) -> list[ProductPrice]:
    return [parse_tile(t) for t in catalog_grid(payload)["items"]]


def is_end_of_catalog(payload: dict) -> bool:
    """Конец каталога на Ozon: виджет грида приходит с error='no data' и без items."""
    for key, raw in (payload.get("widgetStates") or {}).items():
        if key.startswith("tileGridDesktop"):
            grid = json.loads(raw)
            if grid.get("error") == "no data" or (not grid.get("items") and "items" not in grid):
                return True
    return False


# ---------------------------------------------------------------- offline
def run_offline() -> int:
    payload = json.loads((FIXTURES / "catalog_page_1.json").read_text(encoding="utf-8"))
    expected = json.loads((FIXTURES / "catalog_page_1.expected.json").read_text(encoding="utf-8"))
    got = parse_catalog(payload)
    print(f"offline: parsed {len(got)} products from catalog_page_1.json")
    fails = 0
    if len(got) != len(expected):
        print(f"FAIL count: got {len(got)}, expected {len(expected)}")
        fails += 1
    for g, e in zip(got, expected):
        d = asdict(g)
        for field, exp in e.items():
            got_val = d.get(field)
            got_s = str(got_val) if got_val is not None else None
            exp_s = str(exp) if exp not in (None, "") else None
            if got_s != exp_s:
                print(f"FAIL sku={d['sku']} {field}: got={got_s!r} expected={exp_s!r}")
                fails += 1
    for p in got:
        assert p.price is not None, f"{p.sku}: price is None"
        assert p.url.startswith("https://www.ozon.ru/product/"), p.url
        assert p.url.rstrip("/").endswith(p.sku), f"sku не совпадает с URL: {p.url}"
    page2 = json.loads((FIXTURES / "catalog_page_2.json").read_text(encoding="utf-8"))
    skus1 = {p.sku for p in got}
    skus2 = {p.sku for p in parse_catalog(page2)}
    print(f"offline: page1={len(skus1)} sku, page2={len(skus2)} sku, overlap={len(skus1 & skus2)}")
    empty = json.loads((FIXTURES / "catalog_page_empty.json").read_text(encoding="utf-8"))
    end = is_end_of_catalog(empty)
    print("offline: end-of-catalog detected:", end)
    if not end:
        fails += 1
    print("RESULT:", "PASS" if fails == 0 else f"FAIL ({fails})")
    return 0 if fails == 0 else 1


# ---------------------------------------------------------------- live
async def ensure_state(force: bool = False) -> None:
    from playwright.async_api import async_playwright
    if STATE.exists() and not force:
        return
    STATE.parent.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            str(PROFILE), headless=True,
            args=["--disable-blink-features=AutomationControlled"],
            user_agent=UA, locale="ru-RU", viewport={"width": 1440, "height": 900})
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        t0 = time.time()
        await page.goto(SELLER_URL, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(4000)
        html = await page.content()
        if "включите JavaScript" in html or "abt-challenge" in html:
            raise SystemExit("challenge не пройден: нужен headed-режим / ручное прохождение")
        print(f"bootstrap: {page.url} | title={(await page.title())[:60]!r} | {time.time()-t0:.1f}s")
        # Сохраняем в state и подтверждение 18+, чтобы карточки 18+ не отдавали модалку
        await ctx.add_cookies(list(ADULT_COOKIES))
        await ctx.storage_state(path=str(STATE))
        await ctx.close()


async def fetch_page(ctx, n: int) -> dict:
    r = await ctx.request.get(API, params={"url": CATALOG_PAGE_PATH.format(page=n)}, timeout=40000)
    if r.status != 200:
        raise RuntimeError(f"page {n}: HTTP {r.status} {(await r.text())[:120]}")
    return json.loads(await r.body())


async def run_live(args) -> int:
    from playwright.async_api import async_playwright
    await ensure_state(force=args.refresh)
    t0 = time.time()
    rows: list[ProductPrice] = []
    seen: set[str] = set()
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        ctx = await b.new_context(user_agent=UA, locale="ru-RU", storage_state=str(STATE))
        await ensure_adult(ctx)
        for n in range(1, args.pages + 1):
            payload = await fetch_page(ctx, n)
            if is_end_of_catalog(payload):
                print(f"page {n}: конец каталога (error='no data')")
                break
            products = parse_catalog(payload)
            fresh = [x for x in products if x.sku not in seen]
            seen.update(x.sku for x in fresh)
            print(f"page {n}: {len(products)} товаров, новых {len(fresh)}, "
                  f"первый sku {products[0].sku if products else '-'}")
            rows.extend(fresh)
            if args.limit and len(rows) >= args.limit:
                rows = rows[:args.limit]
                break
            await asyncio.sleep(2.5)
        await b.close()

    elapsed = time.time() - t0
    print(f"\n{'sku':>12} | {'price':>9} | {'style':^10} | name")
    for x in rows:
        print(f"{x.sku:>12} | {str(x.price):>9} | {(x.price_style or ''):^10} | {(x.name or '')[:58]}")
    with_price = sum(1 for x in rows if x.price is not None)
    print(f"\nитого: {len(rows)} товаров, с ценой {with_price}, без цены {len(rows)-with_price}, "
          f"время {elapsed:.1f}s, транспорт = browser ctx.request")

    if args.out:
        out = pathlib.Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8") as f:
            for x in rows:
                d = asdict(x)
                d["price"] = str(d["price"]) if d["price"] is not None else None
                d["price_original"] = str(d["price_original"]) if d["price_original"] is not None else None
                f.write(json.dumps(d, ensure_ascii=False) + "\n")
        print(f"записано: {out}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """CLI-парсер вынесен отдельно, чтобы тесты проверяли пути сохранения по умолчанию."""
    ap = argparse.ArgumentParser(description="Шаг 0: разведка каталога Ozon (spike)")
    ap.add_argument("--offline", action="store_true", help="только фикстуры, без сети")
    ap.add_argument("--pages", type=int, default=1)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", default=str(PRICES_FILE),
                    help=f"куда писать JSONL (по умолчанию {PRICES_FILE})")
    ap.add_argument("--refresh", action="store_true", help="пересоздать storage_state")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    if args.offline:
        return run_offline()
    return asyncio.run(run_live(args))


if __name__ == "__main__":
    sys.exit(main())

