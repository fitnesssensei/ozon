"""Тесты дозаполнения карточек: разбор описания и слияние без потерь. Без сети."""
import json
import pathlib
import sys
import tempfile
import unittest

PROJECT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "prototype"))

import download_images  # noqa: E402
import refill_cards  # noqa: E402


class ParseDescriptionTest(unittest.TestCase):
    def test_takes_longest_text(self):
        payload = {"widgetStates": {
            "webDescription-1": json.dumps({
                "shortDescription": "коротко",
                "richAnnotation": {"text": "полное описание " * 20},
            }),
        }}
        result = download_images.parse_description(payload)
        self.assertIn("полное описание", result)
        self.assertGreater(len(result), 100)

    def test_without_description(self):
        self.assertIsNone(download_images.parse_description({"widgetStates": {}}))


class RefillRulesTest(unittest.TestCase):
    def test_needs_refill(self):
        fields = {"description", "rating", "category", "seller"}
        self.assertTrue(refill_cards.needs_refill({"description": None}, fields))
        self.assertTrue(refill_cards.needs_refill({"description": "x" * 200}, fields))
        # Ozon может добить текст пробелами: длина 200 важнее strip()
        self.assertTrue(refill_cards.needs_refill({"description": "x" * 199 + " "}, fields))
        # Полный текст длиннее лимита повторно не запрашиваем
        self.assertFalse(refill_cards.needs_refill({
            "description": "x" * 201, "rating": 4.5,
            "category": ["Книги"], "seller": {"id": 1},
        }, fields))
        self.assertFalse(refill_cards.needs_refill({
            "description": "коротко", "rating": 4.5,
            "category": ["Книги"], "seller": {"id": 1},
        }, fields))
        self.assertTrue(refill_cards.needs_refill({
            "description": "коротко", "rating": None,
            "category": ["Книги"], "seller": {"id": 1},
        }, fields))

    def test_merge_does_not_lose_photos_and_prices(self):
        info = {
            "description": "старое",
            "characteristics": {"Автор": ["А"]},
            "photos": [{"file": "01.jpg"}],
            "price": "100.00",
            "price_card": "90.00",
            "seller": {"id": 7, "name": None},
        }
        card = {
            "rating": 4.8,
            "category": ["Книги", "Проза"],
            "seller": {"id": 999, "name": "Магазин", "url": "https://ozon.ru/seller/x"},
            "price_regular": "120.00",
        }
        chars = {"Автор": ["А", "Б"], "ISBN": ["123"]}
        merged, changes = refill_cards.merge_card(info, card, chars, "новое длинное описание")

        self.assertEqual(merged["photos"], info["photos"])
        self.assertEqual(merged["price"], "100.00")
        self.assertEqual(merged["price_card"], "90.00")
        self.assertEqual(merged["seller"]["id"], 7)  # id из карточки не подменяет старый
        self.assertEqual(merged["seller"]["name"], "Магазин")
        self.assertEqual(merged["characteristics"]["Автор"], ["А", "Б"])
        self.assertEqual(merged["characteristics"]["ISBN"], ["123"])
        self.assertEqual(merged["description"], "новое длинное описание")
        self.assertIn("description", changes)

    def test_merge_keeps_longer_description(self):
        info = {"description": "x" * 100, "characteristics": {}, "photos": []}
        merged, changes = refill_cards.merge_card(info, {}, {}, "коротко")
        self.assertEqual(merged["description"], "x" * 100)
        self.assertNotIn("description", changes)


class DiscoverRootsTest(unittest.TestCase):
    def test_reads_only_shops_with_catalog_cache(self):
        # refill_cards ищет магазины только внутри shops/.
        with tempfile.TemporaryDirectory() as tmp:
            shops = pathlib.Path(tmp) / "shops"
            shops.mkdir()
            with_cache = shops / "shop-a"
            with_cache.mkdir()
            (with_cache / "_books.json").write_text("[]", encoding="utf-8")
            (shops / "shop-b").mkdir()  # без _books.json — не магазин

            old = refill_cards.SHOPS_DIR
            refill_cards.SHOPS_DIR = shops
            try:
                roots = refill_cards.discover_roots()
            finally:
                refill_cards.SHOPS_DIR = old

            self.assertEqual([p.name for p in roots], ["shop-a"])


class LoadTargetsTest(unittest.TestCase):
    def test_only_incomplete(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            for sku, description in (("111", None), ("222", "коротко")):
                folder = root / f"{sku}_book"
                folder.mkdir()
                (folder / "info.json").write_text(json.dumps({
                    "sku": sku, "url": f"https://www.ozon.ru/product/{sku}/",
                    "description": description, "rating": 5, "category": ["Книги"],
                    "seller": {"id": 1}, "characteristics": {"Автор": ["А"]},
                }), encoding="utf-8")
            jobs = refill_cards.load_targets(root, {"description"})
            self.assertEqual([j["info"]["sku"] for j in jobs], ["111"])


if __name__ == "__main__":
    unittest.main()
