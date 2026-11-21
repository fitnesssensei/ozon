#!/usr/bin/env python3
"""Точечное дозаполнение карточек Ozon без перезаписи фото и цен.

Что обновляется в `info.json`:
  - описание (берётся самый длинный текст из `webDescription`);
  - рейтинг, категория, продавец, метки, артикул — только если пустые;
  - характеристики — только отсутствующие ключи или более полные значения.

Фото, цены и `downloaded_at` не трогаются. Запись атомарная:
`info.json.tmp` → `info.json`.

По умолчанию обрабатываются все папки магазинов проекта, у которых есть
`_books.json`. Можно указать конкретные папки через `--out` (несколько раз).

Запуск:
    python3 prototype/refill_cards.py --dry-run
    python3 prototype/refill_cards.py --only description --limit 10
    python3 prototype/refill_cards.py --all --delay 5
"""
import argparse
import asyncio
import copy
import json
import pathlib
import sys

from playwright.async_api import async_playwright

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from download_images import (BASE_URL, parse_card, parse_chars,  # noqa: E402
                             parse_description)
from poc_ozon_prices import API, STATE, UA, ensure_adult, ensure_state  # noqa: E402
from shop_config import SHOPS_DIR  # noqa: E402

DESCRIPTION_LIMIT = 200


def needs_refill(info: dict, fields: set[str]) -> bool:
    """Нужно ли перезапрашивать карточку по выбранным полям."""
    if "all" in fields:
        return True
    if "description" in fields:
        raw_description = info.get("description") or ""
        description = raw_description.strip()
        # Пусто или ровно 200 символов (лимит shortDescription) — нужен
        # полный текст. Всё, что длиннее 200, уже считается полным.
        if not description or len(raw_description) == DESCRIPTION_LIMIT:
            return True
    if "rating" in fields and info.get("rating") is None:
        return True
    if "category" in fields and not info.get("category"):
        return True
    if "seller" in fields and not info.get("seller"):
        return True
    if "chars" in fields and not info.get("characteristics"):
        return True
    return False


def merge_card(info: dict, card: dict, chars: dict,
               description: str | None) -> tuple[dict, list[str]]:
    """Слить новые данные в info.json, не ухудшая уже сохранённое."""
    merged = copy.deepcopy(info)
    changes: list[str] = []

    old_description = (merged.get("description") or "").strip()
    new_description = (description or "").strip()
    if new_description and len(new_description) > len(old_description):
        merged["description"] = new_description
        changes.append("description")

    old_chars = merged.get("characteristics") or {}
    for key, values in (chars or {}).items():
        if not values:
            continue
        if not old_chars.get(key) or len(values) > len(old_chars[key]):
            old_chars[key] = values
            changes.append(f"characteristics:{key}")
    merged["characteristics"] = old_chars

    for field in ("rating", "category", "labels", "article", "name"):
        new_value = card.get(field)
        if new_value and not merged.get(field):
            merged[field] = new_value
            changes.append(field)

    old_seller = merged.get("seller") or {}
    sales_changed = False
    for key, value in (card.get("seller") or {}).items():
        # id не подменяем: parse_card берёт его из текущего shop_config,
        # а карточки могут принадлежать разным магазинам.
        if key == "id" or not value or old_seller.get(key):
            continue
        old_seller[key] = value
        sales_changed = True
    if sales_changed:
        merged["seller"] = old_seller
        changes.append("seller")

    # Цены не обновляем, но пустые значения можем заполнить.
    for field in ("price_card", "price_regular", "available"):
        if merged.get(field) is None and card.get(field) is not None:
            merged[field] = card[field]
            changes.append(field)

    return merged, changes
def load_targets(root: pathlib.Path, fields: set[str], limit: int = 0) -> list[dict]:
    """Найти карточки, которым нужно дозаполнение."""
    jobs: list[dict] = []
    for folder in sorted(p for p in root.iterdir() if p.is_dir()):
        info_path = folder / "info.json"
        if not info_path.exists():
            continue
        try:
            info = json.loads(info_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if needs_refill(info, fields):
            jobs.append({"folder": folder, "info": info})
            if limit and len(jobs) >= limit:
                break
    return jobs


def discover_roots() -> list[pathlib.Path]:
    """Все папки магазинов в shops/, где уже есть каталог _books.json."""
    if not SHOPS_DIR.is_dir():
        return []
    return sorted(p for p in SHOPS_DIR.iterdir()
                  if p.is_dir() and (p / "_books.json").exists())


async def fetch_payload(ctx, path: str) -> dict:
    """Запросить JSON карточки; 3 попытки, как в download_images.py."""
    for attempt in (1, 2, 3):
        response = await ctx.request.get(API, params={"url": path}, timeout=40000)
        if response.status == 200:
            return json.loads(await response.body())
        print(f"  HTTP {response.status}, попытка {attempt}/3", flush=True)
        await asyncio.sleep(5 * attempt)
    return {}


async def refill_one(ctx, job: dict, sem: asyncio.Semaphore, idx: int, total: int,
                     delay: float, dry_run: bool, fields: set[str]) -> tuple[bool, int]:
    """Обработать одну книгу. Вернуть (изменилась ли, число изменений)."""
    async with sem:
        info = job["info"]
        path = info["url"].replace(BASE_URL, "")
        try:
            payload = await fetch_payload(ctx, path)
            if not payload:
                print(f"[{idx}/{total}] {info.get('sku')}: карточка не пришла", flush=True)
                return False, 0

            card = parse_card(payload)
            description = parse_description(payload)

            # Второй фрагмент нужен только для характеристик или если
            # основной ответ не дал полного описания.
            chars: dict = {}
            need_chars = "chars" in fields or "all" in fields
            need_second_description = (
                "description" in fields and len(description or "") <= DESCRIPTION_LIMIT
            )
            if need_chars or need_second_description:
                response = await ctx.request.get(
                    API, params={"url": path + "?layout_container=pdpPage2column&layout_page_index=2"},
                    timeout=40000)
                if response.status == 200:
                    second = json.loads(await response.body())
                    chars = parse_chars(second)
                    second_description = parse_description(second)
                    if second_description and len(second_description) > len(description or ""):
                        description = second_description

            merged, changes = merge_card(info, card, chars, description)
            if not changes:
                print(f"[{idx}/{total}] {info.get('sku')}: без изменений", flush=True)
                return False, 0
            if dry_run:
                print(f"[{idx}/{total}] {info.get('sku')}: будет {', '.join(changes)}",
                      flush=True)
                return True, len(changes)

            tmp = job["folder"] / "info.json.tmp"
            tmp.write_text(json.dumps(merged, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.rename(job["folder"] / "info.json")
            print(f"[{idx}/{total}] {info.get('sku')}: {', '.join(changes)}", flush=True)
            return True, len(changes)
        except Exception as exc:  # noqa: BLE001 — одна книга не должна ронять весь прогон
            print(f"[{idx}/{total}] {info.get('sku')}: ошибка {exc!r}", flush=True)
            return False, 0
        finally:
            await asyncio.sleep(delay)

async def run(args) -> int:
    fields = {f.strip() for f in args.fields.split(",") if f.strip()}
    if args.all:
        fields = {"all"}
    roots = ([pathlib.Path(p).resolve() for p in args.out] if args.out
             else discover_roots())
    if not roots:
        print("не найдено папок магазинов с _books.json")
        return 1

    all_jobs: list[tuple[pathlib.Path, list[dict]]] = []
    remaining = args.limit
    for root in roots:
        if not root.is_dir():
            print(f"нет папки: {root}")
            return 1
        jobs = load_targets(root, fields)
        if args.limit:
            jobs = jobs[:max(0, remaining)]
            remaining -= len(jobs)
        all_jobs.append((root, jobs))
        print(f"{root}: к дозаполнению {len(jobs)} книг", flush=True)
        if args.limit and remaining <= 0:
            break

    total = sum(len(jobs) for _, jobs in all_jobs)
    print(f"всего книг: {total}, поля: {', '.join(sorted(fields))}")
    if total == 0:
        return 0
    if args.dry_run:
        return 0

    await ensure_state()
    changed = changes_count = 0
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True, args=["--disable-blink-features=AutomationControlled"])
        ctx = await browser.new_context(user_agent=UA, locale="ru-RU",
                                        storage_state=str(STATE))
        await ensure_adult(ctx)
        sem = asyncio.Semaphore(1)  # строго последовательно, без параллельности
        idx = 0
        for _root, jobs in all_jobs:
            for job in jobs:
                idx += 1
                was_changed, count = await refill_one(
                    ctx, job, sem, idx, total, args.delay, False, fields)
                changed += int(was_changed)
                changes_count += count
        await browser.close()

    print(f"\nготово: изменено {changed} книг, полей {changes_count}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Дозаполнение карточек Ozon")
    ap.add_argument("--out", action="append",
                    help="папка магазина; можно несколько раз (по умолчанию все)")
    ap.add_argument("--fields", default="description,rating,category,seller",
                    help="какие поля проверять (description,rating,category,seller,chars)")
    ap.add_argument("--all", action="store_true", help="перезапросить все карточки")
    ap.add_argument("--limit", type=int, default=0, help="0 = без лимита")
    ap.add_argument("--delay", type=float, default=2.5, help="пауза между книгами, сек")
    ap.add_argument("--dry-run", action="store_true",
                    help="только показать, что будет обновлено")
    args = ap.parse_args()
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())

