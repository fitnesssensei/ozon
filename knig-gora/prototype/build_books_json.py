#!/usr/bin/env python3
"""Собрать все info.json магазинов в один books.json.

Формат значений — сырой, без нормализации:
  - category   = category[2] (жанр Ozon);
  - publisher  = category[3] (бренд/издательство Ozon);
  - author     = все значения characteristics["Автор"] через запятую;
  - title      = полный name, включая "| Автор | Книга б/у";
  - pages/year/dimensions/weight/isbn/language — строки как есть.

По умолчанию результат пишется в корень проекта: ozon/books.json.
"""
import argparse
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from shop_config import PROJECT_DIR, SHOPS_DIR  # noqa: E402

DEFAULT_OUT = PROJECT_DIR.parent / "books.json"
KEY_ORDER = [
    "category", "author", "title", "publisher", "binding", "pages",
    "year", "dimensions", "weight", "isbn", "language", "annotation",
]


def first(chars: dict, key: str):
    """Первое значение характеристики как есть; иначе None."""
    value = chars.get(key)
    if isinstance(value, list):
        return value[0] if value else None
    return value


def authors(chars: dict):
    """Автор(ы) как есть; несколько значений сохраняем через запятую."""
    value = chars.get("Автор") or chars.get("Автор на обложке")
    if not value:
        return None
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return str(value)


def book_entry(info: dict) -> dict:
    """Одна книга в формате books.json."""
    chars = info.get("characteristics") or {}
    category = info.get("category") or []
    return {
        "category": category[2] if len(category) >= 3 else None,
        "author": authors(chars),
        "title": info.get("name"),
        "publisher": category[3] if len(category) >= 4 else None,
        "binding": first(chars, "Тип обложки"),
        "pages": first(chars, "Количество страниц"),
        "year": first(chars, "Год выпуска"),
        "dimensions": first(chars, "Размеры, мм"),
        "weight": first(chars, "Вес товара, г"),
        "isbn": first(chars, "ISBN"),
        "language": first(chars, "Язык издания"),
        "annotation": info.get("description"),
    }

def discover_roots() -> list[pathlib.Path]:
    """Все папки магазинов в shops/, где есть каталог _books.json."""
    if not SHOPS_DIR.is_dir():
        return []
    return sorted(p for p in SHOPS_DIR.iterdir()
                  if p.is_dir() and (p / "_books.json").exists())


def build(roots: list[pathlib.Path]) -> list[dict]:
    """Прочитать все info.json и вернуть список книг."""
    books: list[dict] = []
    for root in roots:
        for info_path in sorted(root.glob("*/info.json")):
            info = json.loads(info_path.read_text(encoding="utf-8"))
            books.append(book_entry(info))
    return books


def main() -> int:
    ap = argparse.ArgumentParser(description="Сборка books.json из info.json")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="куда писать books.json")
    ap.add_argument("--shops", action="append",
                    help="папка магазина; можно несколько раз (по умолчанию все)")
    args = ap.parse_args()

    roots = ([pathlib.Path(p).resolve() for p in args.shops] if args.shops
             else discover_roots())
    if not roots:
        print("не найдено папок магазинов с _books.json")
        return 1
    missing = [str(root) for root in roots if not root.is_dir()]
    if missing:
        print("нет папок: " + ", ".join(missing))
        return 1

    books = build(roots)
    out = pathlib.Path(args.out).resolve()
    tmp = out.with_name(out.name + ".tmp")
    tmp.write_text(json.dumps(books, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    tmp.replace(out)
    print(f"создан: {out}")
    print(f"книг: {len(books)}")
    for root in roots:
        print(f"  {root.name}: {sum(1 for _ in root.glob('*/info.json'))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
