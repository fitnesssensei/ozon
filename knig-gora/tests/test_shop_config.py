"""Тесты конфигурации магазина.

Проверяем, что все магазинные данные (slug, имя, seller id, URL) живут только
в `prototype/shop_config.py`, а скрипты берут их оттуда и продолжают разбирать
реальный контракт Ozon на фикстурах. Сеть не используется.
"""
import json
import pathlib
import sys
import tempfile
import unittest

PROJECT = pathlib.Path(__file__).resolve().parent.parent
PROTO = PROJECT / "prototype"
sys.path.insert(0, str(PROTO))

import download_images  # noqa: E402
import poc_ozon_prices  # noqa: E402
import shop_config  # noqa: E402


class ShopConfigTest(unittest.TestCase):
    def test_urls_built_from_slug(self):
        self.assertEqual(shop_config.SELLER_URL,
                         f"https://www.ozon.ru/seller/{shop_config.SLUG}/products/")
        self.assertEqual(shop_config.CATALOG_PAGE_PATH.format(page=1),
                         f"/seller/{shop_config.SLUG}/products/?page=1")
        self.assertEqual(shop_config.CATALOG_PAGE_PATH.format(page=110),
                         f"/seller/{shop_config.SLUG}/products/?page=110")

    def test_scripts_use_config(self):
        # Скрипты не держат собственных копий магазинных констант
        self.assertEqual(poc_ozon_prices.SELLER_URL, shop_config.SELLER_URL)
        self.assertEqual(download_images.ROOT, shop_config.IMAGES_DIR)
        self.assertEqual(download_images.SELLER_ID, shop_config.SELLER_ID)

    def test_save_locations(self):
        # Все места сохранения заданы в shop_config.py
        self.assertEqual(download_images.ROOT, shop_config.IMAGES_DIR)
        self.assertEqual(shop_config.PRICES_FILE.parent, shop_config.PRICES_DIR)
        self.assertIn(shop_config.SLUG, shop_config.PRICES_FILE.name)
        self.assertEqual(shop_config.PRICES_FILE.suffix, ".jsonl")
        self.assertEqual(poc_ozon_prices.STATE, shop_config.STATE_FILE)
        self.assertEqual(poc_ozon_prices.PROFILE, shop_config.PROFILE_DIR)

    def test_shops_dir_layout(self):
        # Все магазины лежат в одной папке shops/, а не в корне проекта.
        self.assertEqual(shop_config.SHOPS_DIR, shop_config.PROJECT_DIR / "shops")
        self.assertEqual(shop_config.IMAGES_DIR.parent, shop_config.SHOPS_DIR)
        self.assertEqual(shop_config.IMAGES_DIR.name, "staraya-kniga")

    def test_prices_default_out(self):
        # Без --out срез цен пишется в путь из конфига, а не теряется
        args = poc_ozon_prices.build_parser().parse_args([])
        self.assertEqual(args.out, str(shop_config.PRICES_FILE))

    def test_slug_format(self):
        # Полный URL в SLUG — типовая ошибка, из-за которой ломаются все запросы
        shop_config._validate_slug(shop_config.SLUG)
        for bad in ("https://www.ozon.ru/seller/mir-knig-3479344",
                    "mir-knig-3479344/products/", "", "Мир книг"):
            with self.assertRaises(ValueError):
                shop_config._validate_slug(bad)

    def test_adult_cookies(self):
        # 18+ карточки Ozon отдаёт только с cookie подтверждения возраста
        class FakeCtx:
            def __init__(self):
                self.jar = []

            async def cookies(self):
                return list(self.jar)

            async def add_cookies(self, items):
                self.jar.extend(items)

        import asyncio
        ctx = FakeCtx()
        asyncio.run(poc_ozon_prices.ensure_adult(ctx))
        names = {c["name"] for c in ctx.jar}
        self.assertEqual(names, {"is_adult_confirmed", "adult_user_birthdate"})
        # повторный вызов не должен дублировать cookie
        asyncio.run(poc_ozon_prices.ensure_adult(ctx))
        self.assertEqual(len(ctx.jar), 2)

    def test_no_store_data_outside_config(self):
        forbidden = (shop_config.SLUG, str(shop_config.SELLER_ID), shop_config.TITLE)
        for path in sorted(PROTO.glob("*.py")):
            if path.name == "shop_config.py":
                continue
            text = path.read_text(encoding="utf-8")
            for value in forbidden:
                self.assertNotIn(
                    value, text,
                    f"{path.name}: магазинные данные должны быть только в shop_config.py")

    def test_folder_name_without_sku(self):
        # Новые папки должны совпадать со старой схемой без SKU-префикса.
        self.assertEqual(
            download_images.folder_name(
                "123", "https://www.ozon.ru/product/kak-napisat-123/"),
            "kak-napisat")

    def test_duplicate_folder_gets_number(self):
        # При совпадении slug папка получает номер: 1_, 2_ и далее.
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "book").mkdir()
            (root / "1_book").mkdir()
            name = download_images.unique_folder_name(
                root, "999", "https://www.ozon.ru/product/book-999/",
                {"book", "1_book"})
            self.assertEqual(name, "2_book")

    def test_offline_parser_contract(self):
        fixture = PROJECT / "fixtures" / "catalog_page_1.json"
        payload = json.loads(fixture.read_text(encoding="utf-8"))
        products = poc_ozon_prices.parse_catalog(payload)
        self.assertEqual(len(products), 8)
        self.assertTrue(all(p.price is not None for p in products))
        self.assertTrue(all(p.url.startswith(shop_config.BASE_URL + "/product/")
                            for p in products))


if __name__ == "__main__":
    unittest.main()
