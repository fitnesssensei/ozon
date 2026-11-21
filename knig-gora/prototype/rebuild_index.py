#!/usr/bin/env python3
"""Пересобирает images/index.json + index.csv из папок images/*/info.json.

Полезно, если прогон скачивания был прерван: файлы уже есть, а индекс не дописан.
Запуск: python3 prototype/rebuild_index.py [--out images]
"""
import argparse
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from download_images import dump_index, index_entry, write_readme  # noqa: E402
from shop_config import IMAGES_DIR  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(IMAGES_DIR))
    args = ap.parse_args()

    root = pathlib.Path(args.out).resolve()
    root.mkdir(parents=True, exist_ok=True)
    write_readme(root)

    books, broken = [], 0
    for folder in sorted(p for p in root.iterdir() if p.is_dir()):
        info_file = folder / "info.json"
        if not info_file.exists():
            continue
        try:
            info = json.loads(info_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            broken += 1
            continue
        books.append(index_entry(info))

    dump_index(root, books)
    files = sum(1 for b in books for _ in b["photos"])
    print(f"пересобрано: {len(books)} книг, {files} фото"
          f"{f', битых info.json: {broken}' if broken else ''} -> {root / 'index.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
