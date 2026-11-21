"""Конфигурация магазина Ozon — единственное место с данными конкретного продавца.

Все скрипты прототипа (`poc_ozon_prices.py`, `download_images.py`, `repair.py`,
`rebuild_index.py`, `make_gallery_html.py`) берут магазин только отсюда, поэтому
переключение на другой магазин = правка этого файла (код скриптов не трогаем).

Как направить парсер на другой магазин:
  1. поменяйте `SLUG` (часть URL `/seller/<slug>/`), `TITLE` и `SELLER_ID`;
  2. поменяйте пути сохранения `IMAGES_DIR` и `PRICES_FILE`, иначе данные двух
     магазинов смешаются в одной папке и в одном кеше каталога `_books.json`;
  3. проверьте офлайн-контракт: `python3 prototype/poc_ozon_prices.py --offline`;
  4. сделайте smoke на одну страницу: `python3 prototype/poc_ozon_prices.py --pages 1`.

Домен Ozon один для всех магазинов, поэтому cookie/session (`STATE_FILE`)
переключать не нужно — они живут на `.ozon.ru`, а не на продавце.
"""
import pathlib
import re

# ---------------------------------------------------------------- магазин
# slug продавца из https://www.ozon.ru/seller/<SLUG>/ — только часть после /seller/,
# без домена и без /products/ (например: mir-knig-3479344)
# Предыдущие магазины (для быстрого возврата):
#SLUG = "knig-gora"
#SLUG = "knizhnyy-second-hand-3296276"
#SLUG = "mir-knig-3479344"
#SLUG = "more-knig-3421690"
SLUG = "staraya-kniga-3369147"


# Отображаемое имя — только для README/HTML-галереи, на разбор не влияет
#TITLE = "Книг Гора"
#TITLE = "Книжный Секонд-хенд"
#TITLE = "Мир книг"
#TITLE = "Море книг"
TITLE = "Старая книга"

# Числовой id продавца (pageInfo.analyticsInfo.sellerId) — пишется в info.json
#SELLER_ID = 3359443
#SELLER_ID = 3296276
#SELLER_ID = 3479344
#SELLER_ID = 3421690
SELLER_ID = 3369147

# Защита от типовой ошибки: в SLUG легко случайно вставить полный URL
def _validate_slug(value: str) -> None:
    """SLUG — только буквы/цифры/дефис, без домена и слешей."""
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", value):
        raise ValueError(
            "SLUG должен быть только slug продавца (буквы/цифры/дефис), "
            f"например 'mir-knig-3479344', а не {value!r}")


_validate_slug(SLUG)

# ---------------------------------------------------------------- URL-ы
BASE_URL = "https://www.ozon.ru"
# Страница магазина для bootstrap сессии (прогрев cookie)
SELLER_URL = f"{BASE_URL}/seller/{SLUG}/products/"
# Путь JSON-API каталога; подставлять номер страницы через .format(page=N)
CATALOG_PAGE_PATH = f"/seller/{SLUG}/products/?page={{page}}"

# ---------------------------------------------------------------- файлы и места сохранения
# Корень проекта (папка knig-gora)
PROJECT_DIR = pathlib.Path(__file__).resolve().parent.parent

# Все магазины лежат в одной папке shops/, чтобы корень проекта не разрастался.
# Скрипты, которым нужен весь набор магазинов, ищут их именно здесь.
SHOPS_DIR = PROJECT_DIR / "shops"

# 1. Фото, карточки и индексы download_images.py:
#    <папка-книги>/NN.jpg, <папка-книги>/info.json, index.json, index.csv,
#    README.md, _books.json (кеш каталога), _errors.jsonl
# Предыдущие папки (для быстрого возврата):
#IMAGES_DIR = SHOPS_DIR / "KnigGora"
#IMAGES_DIR = SHOPS_DIR / "knizhnyy-second-hand"
#IMAGES_DIR = SHOPS_DIR / "mir-knig"
#IMAGES_DIR = SHOPS_DIR / "more-knig"
IMAGES_DIR = SHOPS_DIR / "staraya-kniga"

# 2. Срез цен poc_ozon_prices.py: одна строка JSONL = один товар
PRICES_DIR = PROJECT_DIR / "prototype" / "out"
PRICES_FILE = PRICES_DIR / f"prices_{SLUG}.jsonl"

# 3. Сессия Playwright (cookie Ozon) — общая для всех магазинов домена .ozon.ru
STATE_DIR = pathlib.Path("/tmp/ozon_state")
STATE_FILE = STATE_DIR / "poc_storage_state.json"
PROFILE_DIR = STATE_DIR / "profile"
