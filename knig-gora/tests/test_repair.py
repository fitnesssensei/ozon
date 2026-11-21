"""Тесты repair.plan: какие карточки требуют дозаполнения. Без сети."""
import json
import pathlib
import sys
import tempfile
import unittest

PROJECT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "prototype"))

import repair  # noqa: E402


def make_book(root: pathlib.Path, sku: str, chars: dict, listed: list[str],
              files: list[str]) -> None:
    """Создать папку книги с info.json и указанными файлами фото."""
    folder = root / f"{sku}_book"
    folder.mkdir()
    info = {
        "sku": sku,
        "url": f"https://www.ozon.ru/product/book-{sku}/",
        "characteristics": chars,
        "photos": [{"file": name} for name in listed],
    }
    (folder / "info.json").write_text(json.dumps(info), encoding="utf-8")
    for name in files:
        (folder / name).write_bytes(b"x")


class RepairPlanTest(unittest.TestCase):
    def test_plan_only_incomplete(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            make_book(root, "111", {"Автор": ["A"]}, ["01.jpg"], ["01.jpg"])
            make_book(root, "222", {}, ["01.jpg"], ["01.jpg"])
            make_book(root, "333", {"Автор": ["A"]}, ["01.jpg"], [])

            jobs = repair.plan(root)
            self.assertEqual([j["info"]["sku"] for j in jobs], ["222", "333"])
            by_sku = {j["info"]["sku"]: j for j in jobs}
            self.assertTrue(by_sku["222"]["need_chars"])
            self.assertFalse(by_sku["222"]["need_photos"])
            self.assertFalse(by_sku["333"]["need_chars"])
            self.assertTrue(by_sku["333"]["need_photos"])


if __name__ == "__main__":
    unittest.main()
