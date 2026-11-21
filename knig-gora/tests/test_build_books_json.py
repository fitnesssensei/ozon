"""Тесты сборки books.json: сырой маппинг без потерь. Без сети."""
import json
import pathlib
import sys
import tempfile
import unittest

PROJECT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "prototype"))

import build_books_json  # noqa: E402


class BookEntryTest(unittest.TestCase):
    def test_raw_mapping(self):
        info = {
            "name": "Книга | Автор | Книга б/у",
            "category": ["Книги", "Художественная литература", "Проза", "АСТ"],
            "description": "Аннотация",
            "characteristics": {
                "Автор": ["Иванов Иван", "Петров Петр"],
                "Тип обложки": ["Твердый переплет"],
                "Количество страниц": ["638"],
                "Год выпуска": ["2010"],
                "Размеры, мм": ["220х140х30"],
                "Вес товара, г": ["557"],
                "ISBN": ["978-5-367-01587-4"],
                "Язык издания": ["Русский"],
            },
        }
        entry = build_books_json.book_entry(info)
        self.assertEqual(entry["category"], "Проза")
        self.assertEqual(entry["publisher"], "АСТ")
        self.assertEqual(entry["author"], "Иванов Иван, Петров Петр")
        self.assertEqual(entry["title"], "Книга | Автор | Книга б/у")
        self.assertEqual(entry["binding"], "Твердый переплет")
        self.assertEqual(entry["pages"], "638")
        self.assertEqual(entry["year"], "2010")
        self.assertEqual(entry["dimensions"], "220х140х30")
        self.assertEqual(entry["weight"], "557")
        self.assertEqual(entry["isbn"], "978-5-367-01587-4")
        self.assertEqual(entry["language"], "Русский")
        self.assertEqual(entry["annotation"], "Аннотация")
        self.assertEqual(list(entry), build_books_json.KEY_ORDER)

    def test_empty_fields_are_null(self):
        entry = build_books_json.book_entry({"name": "Книга", "characteristics": {}})
        self.assertIsNone(entry["category"])
        self.assertIsNone(entry["publisher"])
        self.assertIsNone(entry["author"])
        self.assertIsNone(entry["pages"])


class DiscoverRootsTest(unittest.TestCase):
    def test_reads_only_shops_with_catalog_cache(self):
        # build_books_json ищет магазины только внутри shops/.
        with tempfile.TemporaryDirectory() as tmp:
            shops = pathlib.Path(tmp) / "shops"
            shops.mkdir()
            with_cache = shops / "shop-a"
            with_cache.mkdir()
            (with_cache / "_books.json").write_text("[]", encoding="utf-8")
            (shops / "shop-b").mkdir()  # без _books.json — не магазин

            old = build_books_json.SHOPS_DIR
            build_books_json.SHOPS_DIR = shops
            try:
                roots = build_books_json.discover_roots()
            finally:
                build_books_json.SHOPS_DIR = old

            self.assertEqual([p.name for p in roots], ["shop-a"])


class BuildTest(unittest.TestCase):
    def test_reads_all_books(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            for sku in ("111", "222"):
                folder = root / f"{sku}_book"
                folder.mkdir()
                (folder / "info.json").write_text(json.dumps({
                    "name": f"Книга {sku}",
                    "category": ["Книги", "Проза", "Роман", "АСТ"],
                    "characteristics": {"Автор": ["Автор"]},
                }), encoding="utf-8")
            books = build_books_json.build([root])
            self.assertEqual([b["title"] for b in books], ["Книга 111", "Книга 222"])


if __name__ == "__main__":
    unittest.main()
