# Парсер магазинов на Ozon: актуальное состояние и история плана

Код — `knig-gora/prototype/`. Все параметры магазина — `prototype/shop_config.py`.
§0 — актуальная шпаргалка (19.11.2026); §1–§12 — исходный план от 18.11.2026.

https://www.ozon.ru/seller/knig-gora/ — «Книг Гора», 848 книг
https://www.ozon.ru/seller/knizhnyy-second-hand-3296276/ — «Книжный Секонд-хенд», 332
https://www.ozon.ru/seller/mir-knig-3479344/ — «Мир книг», 138
https://www.ozon.ru/seller/more-knig-3421690/ — «Море книг», 130
https://www.ozon.ru/seller/staraya-kniga-3369147/ — «Старая книга», 454


(в `Sobes` код не пишем — здесь только знание и планы).

---

## 0. Актуальное состояние (19.11.2026)

### Где что лежит

- **Код:** `knig-gora/prototype/` — отдельного репозитория `ozon-price-scraper` нет.
- **Единственный источник данных магазина:** `prototype/shop_config.py`.
- **Скрипты:** `poc_ozon_prices.py` (цены), `download_images.py` (фото + карточки),
  `repair.py` (дозаполнение), `rebuild_index.py` (индексы), `make_gallery_html.py` (HTML).
- **Тесты:** `knig-gora/tests/` — `unittest` (pytest в системе не установлен).
- **Фикстуры:** `knig-gora/fixtures/` — реальные payload'ы каталога для офлайн-проверки.

### Скачанные магазины

| Магазин | SLUG | sellerId | TITLE | Папка | Книг | Фото | Без характеристик |
|---|---|---|---:|---|---:|---:|---:|
| Книг Гора | `knig-gora` | 3359443 | Книг Гора | `shops/KnigGora` | 848 | 5 084 | 0 |
| Книжный Секонд-хенд | `knizhnyy-second-hand-3296276` | 3296276 | Книжный Секонд-хенд | `shops/knizhnyy-second-hand` | 332 | 1 780 | 0 |
| Мир книг | `mir-knig-3479344` | 3479344 | Мир книг | `shops/mir-knig` | 138 | 400 | 0 |
| Море книг | `more-knig-3421690` | 3421690 | Море книг | `shops/more-knig` | 130 | 479 | 0 |
| Старая книга | `staraya-kniga-3369147` | 3369147 | Старая книга | `shops/staraya-kniga` | 454 | 2 681 | 0 |
| **Итого** | | | | | **1 902** | **10 424** | **0** |

Цифры — на 19.11.2026. Каталог Ozon меняется: перед новым полным прогоном количество может
отличаться, актуальный снимок хранится в `<папка>/_books.json`.

### Как переключить парсер на другой магазин

Правится **только** `prototype/shop_config.py`:

1. `SLUG` — часть URL после `/seller/`, **без домена и без `/products/`**
   (например `staraya-kniga-3369147`). Полный URL в `SLUG` запрещён — стоит
   проверка `_validate_slug()`, которая упадёт с понятной ошибкой.
2. `TITLE` — отображаемое имя (README/HTML), на разбор не влияет.
3. `SELLER_ID` — `pageInfo.analyticsInfo.sellerId`, пишется в `info.json`.
4. `IMAGES_DIR` — отдельная папка результата; иначе фото и кеш `_books.json`
   двух магазинов смешаются.

`SELLER_URL`, `CATALOG_PAGE_PATH` и `PRICES_FILE` собираются из `SLUG` автоматически.
Предыдущие значения лежат рядом закомментированными — для быстрого возврата.

Проверка после переключения:

```bash
cd /Users/rustamismagilov/Desktop/ozon/knig-gora
python3 prototype/poc_ozon_prices.py --offline          # контракт, без сети -> PASS
python3 prototype/poc_ozon_prices.py --pages 1 --limit 8  # smoke: 8 товаров с ценами
```

### Куда пишутся данные

| Что | Где | Откуда берётся путь |
|---|---|---|
| Фото, `info.json`, `index.json`, `index.csv`, `README.md`, `_books.json`, `_errors.jsonl` | `<IMAGES_DIR>/` | `shop_config.IMAGES_DIR` |
| Срез цен, 1 строка JSONL = 1 товар | `prototype/out/prices_<SLUG>.jsonl` | `shop_config.PRICES_FILE` (он же `--out` по умолчанию) |
| Сессия Playwright (cookie Ozon) | `/tmp/ozon_state/poc_storage_state.json` + `/tmp/ozon_state/profile` | `STATE_FILE` / `PROFILE_DIR` |

`info.json` одной книги: `sku`, `url`, `name`, `folder`, `price`, `price_style`, `price_card`,
`price_regular`, `available`, `rating`, `reviews_count`, `seller`, `category`, `labels`,
`article`, `description`, `characteristics`, `photos[{file, src, bytes}]`, `downloaded_at`.

Важно: **отдельного поля `dimensions` нет**. Размеры, если Ozon их отдал, лежат в
`characteristics["Размеры, мм"]`, вес — в `characteristics["Вес товара, г"]`.
У букинистики эти поля заполняет продавец, поэтому у большинства книг их просто нет —
это не баг парсера.

Запись идёт по одной книге: `info.json` пишется сразу после обработки карточки
(атомарно через `.tmp` → `rename`), `index.json`/`index.csv` пересобираются каждые
10 книг (при `--card-concurrency 1`), финальный индекс — в конце прогона.

### Карточки 18+

Ozon отдаёт карточку 18+ не как товар, а как **один виджет `userAdultModal`**:
нет ни характеристик, ни продавца, ни цены. Симптом в `info.json` — пустой
`characteristics`, `seller: null`, одно фото-обложка.

Решение — те же cookie, что выставляет модалка подтверждения возраста:

```
is_adult_confirmed=true
adult_user_birthdate=1990-01-01
```

Реализовано в `poc_ozon_prices.py`: `ADULT_COOKIES` + `ensure_adult(ctx)`. Вызывается
при bootstrap (cookie попадают в `storage_state`), в живом прогоне цен, в
`download_images.py` и `repair.py`. Новые прогоны 18+ карточки обрабатывают сразу.

Для справки: модалка вызывает `POST /api/composer-api.bx/_action/setBirthdate?isAlco=false`
с телом `{"link":"/","birthdate":"YYYY-MM-DD"}`; ответ выставляет эти cookie.
`page.goto` на карточку даёт `Antibot Captcha`, поэтому используется только `ctx.request`.

### Команды полного прогона

```bash
cd /Users/rustamismagilov/Desktop/ozon/knig-gora

# 1. Контракт без сети
python3 prototype/poc_ozon_prices.py --offline

# 2. Smoke: одна страница
python3 prototype/poc_ozon_prices.py --pages 1 --limit 8

# 3. Все цены до конца каталога (--pages с запасом; цикл сам остановится)
python3 prototype/poc_ozon_prices.py --pages 999
# -> prototype/out/prices_<SLUG>.jsonl (путь по умолчанию из shop_config)

# 4. Все фото и карточки
python3 prototype/download_images.py
# Полезные флаги:
#   --delay 5 --card-concurrency 1 --img-workers 2   щадящий режим
#   --no-full-chars        без 2-го фрагмента характеристик (вдвое меньше запросов)
#   --refresh-catalog      перечитать каталог, игнорируя _books.json
#   --refresh-info         перезапросить карточки уже скачанных книг
#   --limit-books N        только первые N книг
#   --no-images            только карточки/URL, без файлов
#   --no-resume            не пропускать готовое

# 5. Дозаполнить характеристики/фото в любой папке
python3 prototype/repair.py --out <папка> --concurrency 1 --delay 1.0

# 6. Пересобрать index.json / index.csv без сети
python3 prototype/rebuild_index.py --out <папка>

# 7. HTML-галерея из index.json (пишет index.html в папку магазина)
python3 prototype/make_gallery_html.py
```

Полный обход «Старой книги» (454 книги, 2 681 фото) занял ~1 час; каталог цен — 58 страниц,
~3 минуты. Ориентир: 1 книга ≈ 2.5–6 с в зависимости от числа фото и `--delay`.

### Как считается каталог

- 8 плиток на страницу, `?page=N`, конец — виджет грида с `error: "no data"`.
- Уникальные `sku` дедуплицируются: сумма плиток больше числа книг на величину повторов
  (например, 460 плиток → 449 уникальных).
- Снимок каталога на момент запуска — `<папка>/_books.json`; дальнейшие изменения Ozon
  на текущий прогон не влияют.

### Блокировка по IP (случилась 19.11.2026)

Симптом: `403` на **все** запросы (каталог, карточка, главная) с HTML
«Похоже, нет соединения» (`abt-challenge/incidents`). Свежий профиль без старых cookie
тоже получает 403 — значит режется IP, а не сессия.

Что делать:

1. Подождать 30–60 минут (иногда дольше), не долбить Ozon.
2. Сменить сеть/IP: выключить VPN, перезагрузить роутер, раздать с телефона.
3. Обновить сессию: `python3 prototype/poc_ozon_prices.py --refresh --pages 1 --limit 1 --out /tmp/ozon_check.jsonl`.
4. Снизить темп: `--delay 5 --card-concurrency 1`; не запускать несколько скриптов параллельно.
5. После 3 неудачных попыток карточка пишется как обложка без характеристик — такие
   книги лечатся `repair.py` после разблокировки.

### Тесты

```bash
python3 -m unittest discover -s tests -v   # 9 тестов, без сети
```

Покрыто: URL/пути из `shop_config`, запрет полного URL в `SLUG`, adult-cookie,
неизменность офлайн-контракта, `repair.plan()` (что требует дозаполнения).
`pytest` в системе не установлен — тесты на стандартном `unittest`.

### Ограничения

- `page.goto` на карточку → captcha; транспорт только `ctx.request` / in-page `fetch`.
- Характеристики и размеры приходят только если их заполнил продавец.
- БД нет: цены — JSONL, карточки — `info.json` + индексы.
- Полный обход — нагрузка на Ozon: делать осознанно, с паузами, без параллельных прогонов.

## 1. Задача

> Историческая постановка от 18.11.2026 (один магазин). Актуально — §0: пять магазинов.

- **Магазин:** `https://www.ozon.ru/seller/knig-gora/`
  (каталог магазина: `https://www.ozon.ru/seller/knig-gora/products/`).
- **Что нужно получить:** срез актуальных цен по товарам магазина (до `--limit` штук с первых
  страниц выдачи) **и все фото галерей** товаров — локально, по папке на книгу в `images/`.
- **Что НЕ нужно:** бренд, характеристики, рейтинг, отзывы, описание, история цен.
- **Частота:** по требованию (ручной запуск). Расписание (cron/Airflow) — вне v1.

> **Граница честно:** «цена по каждому товару магазина» в v1 **не достигается** — без прокси
> мы сознательно ограничены 20–50 товарами за прогон (см. §8). Формулировка цели приведена
> в соответствие с этим ограничением, а не оставлена как обещание.

## 2. Скоуп v1

> Исторический скоуп. Фактически реализовано больше: 5 магазинов, `repair.py`, обход 18+.
> Актуальное состояние — §0.

Делаем:

- bootstrap браузерной сессии (Playwright) и переиспользование cookie,
- обход каталога магазина (пагинация до `--pages`/`--limit`),
- извлечение `sku`, `url`, `name`, `price`, `price_original`, `price_style`, `in_stock` из выдачи,
- сохранение среза цен в **JSON** (`prototype/out/prices.jsonl`, `data/prices_<timestamp>.json`),
- **фото**: проход по карточкам товаров, все фото галереи → `shops/<магазин>/<slug>/NN.jpg`,
  `info.json` на книгу, сводные `images/index.json` и `images/index.csv`,
- CLI: `--pages`, `--limit`, `--out`, `--resume`, `--dry-run`, `--log-level`, `--delay`;
- офлайн-проверка контракта на фикстурах: `prototype/poc_ozon_prices.py --offline`.

Не делаем (осознанно, решение 18.11.2026):

- **PostgreSQL и миграции — отложены**; SQL-схема остаётся в §4 «на будущее»,
- историю цен и уведомления о падении (`prev_price`/`price_changed_at` не пишем),
- открытие карточек ради цены, если цены нет в плитке (`price = NULL`),
- характеристики, отзывы, рейтинг, описание,
- расписание (cron) и обход нескольких магазинов,
- **репозиторий, пакет, pytest-набор и CI** — код живёт скриптами в `prototype/`.

## 3. Факты разведки (проверено 18.11.2026)

| Проверка | Результат |
|---|---|
| `curl -I https://www.ozon.ru/seller/knig-gora/products/` | `HTTP/2 307`, `location: ...?__rr=1`, `set-cookie: __Secure-ETC=...` |
| `curl -L` с браузерным `User-Agent` | `403` на `?__rr=1`: HTML челленджа `abt-challenge`, «включите JavaScript» |
| Загрузка страницы обычным HTTP-клиентом **без cookie** | невозможна: Ozon требует JS-прогрев (`?__rr=1`) |

Выводы для архитектуры (по итогам прогонов 18.11.2026):

1. **Челлендж проходится headless-Chromium** (Playwright 1.60, Chrome for Testing 148), без
   headed-режима и без прокси: итоговый URL `...?__rr=1&abt_att=1`, title «Каталог Книг гора»,
   46 ссылок на товары в DOM.
2. **Обычный HTTP-клиент не работает даже с cookie и полными браузерными заголовками**:
   `requests` получает `403 {"incidentId": "fab_..."}`. Режется не cookie, а не-браузерный стек.
   `httpx` в архитектуре **не используется**; проверять его повторно — только при поломке.
3. Рабочий транспорт — **`BrowserContext.request`** (сетевой стек Chromium): 200, ~250–320 КБ,
   0.2–0.6 с на страницу, **без открытия страницы**: `goto` нужен только для bootstrap.
   Параллельность работает: 3 запроса одновременно — 0.42 с суммарно.
4. Fallback — `page.evaluate(fetch)` внутри открытой страницы (тоже 200), если Ozon начнёт
   проверять контекст запроса, а не только стек.
5. Bootstrap обязателен один раз: `storage_state.json` + persistent-профиль. Cookie живут
   часы–сутки → `SessionExpired` → перепрогрев → один повтор.
6. Пагинация `?page=N` **работает**, подтверждается полем `page` внутри грида.
   `infiniteVirtualPaginator.nextPage` присутствует всегда → **не** является сигналом конца.
7. Прокси: `PROXY_URL` в `.env`. Пусто → прямой IP, пауза 2.5 с, `--concurrency 1`.

### Факты шага 0 (проверено 18.11.2026, headless, без прокси)

| Проверка | Результат |
|---|---|
| HTTP-клиент с cookie после прогрева | **не работает**: `requests` (с полными `sec-ch-ua`/`sec-fetch-*` заголовками) → `403 fab_...` |
| `BrowserContext.request` без открытия страницы | **200**, 250–320 КБ, 0.2–0.6 с |
| `page.evaluate(fetch)` внутри страницы | 200 (fallback) |
| Фактический URL JSON-API | `https://www.ozon.ru/api/entrypoint-api.bx/page/json/v2?url=/seller/knig-gora/products/?page=N` |
| Виджет каталога магазина | `tileGridDesktop-3669724-default-1`, 8 плиток, `header = null` |
| «Чужие» плитки в том же ответе | рекомендации `tileGridDesktop-14036369-default-1` («Возможно, вам понравится»), 30 плиток: молоко, куртки, мороженое |
| Признак плитки каталога | есть `brandLogo`, нет `sellerId`/`sellerName` (фильтровать по продавцу в плитке нельзя) |
| `sellerId` | 3359443 — в `pageInfo.analyticsInfo`, не в плитках |
| Плиток на странице | ровно **8**; `?page=N` работает, `grid.page = N` подтверждает |
| Конец каталога | виджет грида приходит как `{"error": "no data"}` (без `items`) |
| `nextPage` пагинатора | присутствует **всегда**, в том числе на пустой странице → сигналом конца не является |
| Размер каталога | **869 товаров / 109 страниц** (последняя страница — 5 товаров) |
| Формат цены | `mainState[].priceV2.price[]` = `[{text: "1 490 ₽", textStyle: "PRICE"}, …]`, стиль в `priceV2.priceStyle.styleType` |
| Наблюдённые `styleType` | `CARD_PRICE` (каталог магазина, одна цена), `SALE_PRICE` (рекомендации, есть `ORIGINAL_PRICE`) |
| Отдельная «цена без Ozon Карты» | в payload **отсутствует** — в каталоге приходит одна цена со `styleType: CARD_PRICE` |
| Имя товара | `mainState[].textDS` с `testInfo.automatizationId == "tile-name"` (в рекомендациях — ещё и `id: "name"`) |
| Ссылка | `action.link` = `/product/<slug>-<sku>/?at=<tracking>` (относительная, трекинг-параметр отбрасываем) |
| Плитка без цены / «нет в наличии» | **не встречена** (30/30 и 8/8 плиток с ценой) — правило для неё остаётся непроверенным |
| `403/429` при быстром повторе | не воспроизведено: 3 параллельных запроса — 0.42 с, ошибок нет |
| Оценка полного прогона | 109 × (0.3 с + 2.5 с паузы) ≈ **5 мин** на весь каталог |

### Артефакты разведки и как воспроизвести

- `fixtures/catalog_page_1.json` — реальный ответ API (только нужные виджеты: каталог, пагинатор,
  карточка магазина), `catalog_page_2.json`, `catalog_page_empty.json` (конец каталога).
- `fixtures/catalog_page_1.expected.json` — эталонный разбор: 8 товаров с `sku/url/name/price/price_style`.
- `prototype/poc_ozon_prices.py` — spike шага 0 (не репозиторий кода): bootstrap сессии, разбор,
  JSONL. Запуск:

```bash
python3 prototype/poc_ozon_prices.py --offline                 # фикстуры, без сети -> PASS
python3 prototype/poc_ozon_prices.py --pages 3 --limit 24 \
        --out prototype/out/prices.jsonl                       # живой прогон
```

Результат живущего прогона: bootstrap 4.8 с, 3 страницы, **24 товара с ценами** (все `CARD_PRICE`),
6.5 с суммарно, JSONL валиден, `sku` совпадает с URL. Офлайн-сверка с эталоном — **PASS**.

## 4. Схема данных

> **Решение 18.11.2026: в v1 PostgreSQL не используется.** Срез цен пишется в JSON
> (`prototype/out/prices.jsonl`, `data/prices_<timestamp>.json`), БД не нужна.
> Схема ниже сохранена как проект «на будущее» и проверена на PostgreSQL 18 —
> если однажды понадобится история/сравнения, брать её как есть.

Модель в коде (Pydantic v2; конфиг — `pydantic-settings`, см. §5):

```python
from decimal import Decimal
from pydantic import AwareDatetime, BaseModel


class ProductPrice(BaseModel):
    sku: str                        # числовой id товара из URL; TEXT — это ключ, а не число
    url: str                        # каноническая ссылка https://www.ozon.ru/product/<slug>-<sku>/
    name: str | None                # имя с плитки (для сверки глазами), не обязательное
    price: Decimal | None           # цена, которую видит покупатель (правило ниже)
    price_original: Decimal | None  # зачёркнутая цена (ORIGINAL_PRICE), если пришла
    price_style: str | None         # CARD_PRICE | SALE_PRICE | ... (что именно показал Ozon)
    in_stock: bool | None           # True, если цена есть; None — определить не удалось
    parsed_at: AwareDatetime        # UTC, tz-aware; момент извлечения
```

Правило выбора цены (зафиксировано по фактам шага 0, без «угадывания»):

1. `price` = текст из `priceV2.price[]` со `textStyle == "PRICE"` (нормализация: `\u2009`, `\xa0`,
   `₽`, `quantize(0.01)`); это единственная цена, по которой строятся отчёты и `prev_price`;
2. `price_original` = текст с `textStyle == "ORIGINAL_PRICE"` — это **зачёркнутая** цена, а не
   «цена без карты»; в каталоге магазина Ozon её обычно не отдаёт (`NULL` — норма);
3. `price_style` = `priceV2.priceStyle.styleType`. В каталоге приходит `CARD_PRICE`, то есть
   показываемая цена — «с Ozon Картой»; отдельной цены без карты в payload **нет**, поэтому
   колонки `price_card`/`price_regular` не заводим (они были бы всегда `NULL` или дублем);
4. если цены нет — `price = NULL`, `in_stock = NULL` (не `False`: отсутствие цены в плитке ещё
   не доказательство «нет в наличии»); товар сохраняется, попадает в лог как `no_price`;
5. `prev_price`/`price_changed_at` считаются в SQL upsert (см. ниже).

Схема БД (PostgreSQL, срез + метаданные прогонов; история цен не ведётся):

```sql
CREATE TABLE IF NOT EXISTS ozon_prices (
    sku              TEXT PRIMARY KEY,            -- уникальный ключ товара
    url              TEXT        NOT NULL,
    name             TEXT,                        -- имя с плитки (для сверки глазами)
    price            NUMERIC(12,2),               -- цена покупателя; NULL, если цены нет
    price_original   NUMERIC(12,2),               -- зачёркнутая цена (ORIGINAL_PRICE)
    price_style      TEXT,                        -- CARD_PRICE | SALE_PRICE | ...
    in_stock         BOOLEAN,                     -- TRUE, если цена есть; NULL — неизвестно
    currency         TEXT        NOT NULL DEFAULT 'RUB' CHECK (currency ~ '^[A-Z]{3}$'),
    prev_price       NUMERIC(12,2),               -- price предыдущего прогона
    price_changed_at TIMESTAMPTZ,                 -- когда prev_price стал отличаться от price
    run_id           UUID        NOT NULL,        -- прогон, актуализировавший строку
    parsed_at        TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS ozon_prices_run_id_idx ON ozon_prices (run_id);

CREATE TABLE IF NOT EXISTS ozon_runs (
    run_id      UUID PRIMARY KEY,
    started_at  TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    pages       INTEGER NOT NULL DEFAULT 0,
    total       INTEGER NOT NULL DEFAULT 0,
    with_price  INTEGER NOT NULL DEFAULT 0,
    no_price    INTEGER NOT NULL DEFAULT 0,
    blocked     INTEGER NOT NULL DEFAULT 0,
    transport   TEXT,                             -- 'ctx_request' | 'in_page_fetch'
    note        TEXT
);

```

Запрос записи — параметризованный, живёт в `storage.py` (`upsert_prices`) и **не входит в миграцию**:
`psql` не подставит `$1`, а DDL-файл должен применяться как есть. Проверено на временном
кластере PostgreSQL 18 (см. §12, строка «Ревью»).

```sql
-- upsert среза: prev_price/price_changed_at считаем здесь, чтобы отвечать
-- «изменилась ли цена», не ведя историю цен (решение из §2)
INSERT INTO ozon_prices AS p (
    sku, url, name, price, price_original, price_style, in_stock, currency,
    prev_price, price_changed_at, run_id, parsed_at
)
VALUES ($1, $2, $3, $4, $5, $6, $7, 'RUB', NULL, NULL, $8, $9)
ON CONFLICT (sku) DO UPDATE
SET url              = EXCLUDED.url,
    name             = EXCLUDED.name,
    prev_price       = p.price,
    price_changed_at = CASE
                         WHEN p.price IS DISTINCT FROM EXCLUDED.price
                         THEN EXCLUDED.parsed_at
                         ELSE p.price_changed_at
                       END,
    price            = EXCLUDED.price,
    price_original   = EXCLUDED.price_original,
    price_style      = EXCLUDED.price_style,
    in_stock         = EXCLUDED.in_stock,
    currency         = EXCLUDED.currency,
    run_id           = EXCLUDED.run_id,
    parsed_at        = EXCLUDED.parsed_at;
```

Замечания по схеме:

- **`price` — единственное «сравнимое» поле**: по нему считаются `prev_price`, `price_changed_at`
  и отчёты. `price_original`/`price_style` — сырьё, чтобы через месяц не гадать, что именно
  показывал Ozon (`CARD_PRICE` ≠ «обычная цена», это цена с картой).
- **`name`** хранится только для человеческой сверки и отчётов; в отчётных расчётах не участвует.
- **`in_stock`**: `TRUE`, если цена есть; `NULL`, если цены нет (нет доказательства «нет в наличии»).
  В наблюдавшихся 38 плитках товаров без цены не встретилось — правило `NULL` ждёт реального кейса.
- **`run_id`** отличает «товар исчез из магазина» от «товар не попал в этот срез»: строки,
  у которых `run_id` старше текущего прогона, — не подтверждены.
- **История цен не ведётся** (§2), но `prev_price`/`price_changed_at` отвечают на вопрос
  «изменилась ли цена с прошлого прогона». Полная история задним числом невозможна — принято.
- **Миграции** — отдельные файлы `migrations/NNN_*.sql` + идемпотентный раннер.
  `CREATE TABLE IF NOT EXISTS` **не применяет** изменения схемы к существующей таблице,
  поэтому схема живёт в миграциях, а не в коде.
- **Деньги**: `Decimal` в коде (нормализация `\xa0`/`\u2009`/`₽`, `quantize(0.01)`),
  `NUMERIC(12,2)` в БД. Валюта в v1 всегда `RUB`: в модели не хранится (лишнее поле),
  в SQL — литерал, в БД — `CHECK`, чтобы однажды не приехала не та валюта незамеченной.
- **Объём записи**: каталог — 869 товаров; для такого объёма `executemany` уже медленный,
  берём `COPY` в temp-таблицу + один upsert (для 20–50 строк достаточно `executemany`).

### Что пишется в `info.json` (v2, с 18.11.2026)

| Поле | Источник | Пример |
|---|---|---|
| `sku`, `url`, `folder` | каталог | `2839281521` |
| `name` | `webProductHeading.title` | «Амбулаторный прием терапевта \| Боцюрко…» |
| `price` / `price_style` | каталог (`CARD_PRICE`) | `243.00` |
| `price_card`, `price_regular` | `webPrice.cardPrice` / `.price` | `243.00` / `270.00` |
| `available` | `webPrice.isAvailable` | `true` |
| `rating`, `reviews_count` | `webSingleProductScore`, `webReviewProductScore` | `4.8`, `12` |
| `seller` | `webCurrentSeller` | `{id, name, rating, followers, url}` |
| `category` | `breadCrumbs` | `["Книги", "Художественная литература", …]` |
| `labels` | `webMarketingLabels` | `["Постоплата"]` |
| `article` | `webDetailSKU.copyText` | `2839281521` |
| `description` | `webDescription.shortDescription` | текст (180–400 симв.) |
| `characteristics` | **фрагмент 2**: `webCharacteristics` | `{Автор, Серия, Год выпуска, ISBN, Количество страниц, Вес товара, …}` |
| `photos[]` | `webGallery.images[].src` | `01.jpg…NN.jpg` + `src` + `bytes` |
| `downloaded_at` | скрипт | ISO-время |

Фрагмент 2 запрашивается отдельно:
`.../page/json/v2?url=/product/<slug>-<sku>/?layout_container=pdpPage2column&layout_page_index=2`
(~95 КБ, виджет `webCharacteristics`, до 14 характеристик).

Важно: **`page.goto` на карточку уже отдаёт капчу** `Antibot Captcha` (проверено 18.11.2026),
поэтому характеристики берутся через `ctx.request`, а не через открытие страницы.

## 5. Файлы проекта (без репозитория и пакета — решение 18.11.2026)

Актуальная структура (19.11.2026):

```
ozon/
├── ozon.md
└── knig-gora/
    ├── prototype/
    │   ├── shop_config.py        # магазин + пути сохранения (единственное место)
    │   ├── poc_ozon_prices.py    # цены + bootstrap + adult cookies
    │   ├── download_images.py    # фото и карточки
    │   ├── repair.py             # дозаполнение характеристик/фото (--out)
    │   ├── rebuild_index.py      # index.json / index.csv
    │   ├── make_gallery_html.py  # index.html
    │   └── out/                  # срезы цен: prices_<slug>.jsonl
    ├── tests/                    # unittest: shop_config, repair.plan
    ├── fixtures/                 # реальные payload'ы каталога
    └── shops/
        ├── KnigGora/             # 848 книг / 5 084 фото
        ├── knizhnyy-second-hand/ # 332 / 1 780
        ├── mir-knig/             # 138 / 400
        ├── more-knig/            # 130 / 479
        └── staraya-kniga/        # 454 / 2 681
```

Внутри папки магазина: `<slug>/NN.jpg`, `<slug>/info.json`, `index.json`,
`index.csv`, `README.md`, `_books.json` (снимок каталога), `_errors.jsonl`.

Пакет, `pyproject.toml`, pytest-набор, CI и миграции **не создаются** — осознанное решение:
объём задачи не оправдывает инфраструктуру. Проверка корректности = офлайн-сверка с эталоном
(`poc_ozon_prices.py --offline`) плюс детерминированные фикстуры в `fixtures/`.

Зависимости: `playwright` (bootstrap + `BrowserContext.request`), `requests` (скачивание
картинок с публичного CDN). `pydantic`, `asyncpg`, `httpx` — не нужны.

## 6. Этапы работ

Каждый шаг = отдельная проверка + отдельный коммит. Следующий шаг не начинается
без слова «продолжай».

Порядок изменён по ревью: сначала проверяем дешёвый транспорт (шаг 0), затем сразу пишем
bootstrap как продовый модуль (шаг 0.5), а не выбрасываемый скрипт.

### Шаг 0 — разведка — **выполнен 18.11.2026**

Протокол и результаты — в §3 («Факты шага 0»), артефакты — `fixtures/` и `prototype/`.
Кратко: челлендж проходится headless-Chromium; `requests`/`httpx` с теми же cookie блокируются
(`403 fab_*`); рабочий транспорт — `BrowserContext.request`; API —
`entrypoint-api.bx/page/json/v2?url=/seller/knig-gora/products/?page=N`; каталог — отдельный
виджет `tileGridDesktop-3669724-default-1` (8 товаров на страницу, рядом 30 «чужих» плиток
рекомендаций); 869 товаров / 109 страниц; конец каталога — `error: "no data"`.

**Критерий готовности:** выполнен — есть фикстуры реального ответа (38 КБ вместо мегабайт HTML),
эталонный разбор, определены транспорт, пагинация, формат цены и сигнал конца каталога.

Осталось непроверенным (ждёт реального кейса): плитка без цены / «нет в наличии»,
поведение при 403/429 (не воспроизведено), работа через прокси.

### Шаг 0.5 — `bootstrap.py` (прогрев сессии) — **прототип проверен 18.11.2026**

- `async def ensure_session() -> Session`: открыть persistent-профиль
  (`launch_persistent_context(user_data_dir=...)`), прогреть страницу магазина,
  дождаться исчезновения challenge-разметки;
- убрать очевидные признаки автоматизации (`--disable-blink-features=AutomationControlled`,
  `navigator.webdriver`); при детекте headless — зафиксировать это и оставить headed-режим
  как документированный fallback (один ручной прогон);
- сохранить `storage_state.json` (cookie + localStorage) **и** профиль — оба в `.gitignore`;
- `detect_block(page) -> bool`: 307-цикл, капча, текст «Доступ ограничен», отсутствие плиток;
- `SessionExpired` — исключение для сценария «cookie протухли → перепрогрев → один повтор»;
- опция прокси: `launch(proxy={"server": PROXY_URL})`, если `PROXY_URL` задан.

**Проверка:** `python scripts/smoke_browser.py` → печатает итоговый URL, число найденных плиток
и путь к `storage_state.json`.

Проверено прототипом: headless-прогрев занимает **4.8 с**, челлендж проходится, `storage_state.json`
(4.4 КБ) достаточно для последующих `ctx.request` **без повторного `goto`** — это и есть режим
работы воркера. Повторный запуск без `--refresh` к bootstrap не возвращается.

**Критерий готовности:** одна реальная страница открывается, состояние сохраняется и не попадает
в git; прогрев вызывается как функция из CLI.

### Шаг 1 — скелет репозитория — **отменён 18.11.2026**

Репозитория и пакета не будет (§5). Вместо шага 1: `prototype/poc_ozon_prices.py` + `fixtures/`.
Виртуальное окружение не нужно — Playwright и `requests` уже установлены в системе.

### Шаг 2 — `parser.py` + тесты

Вход парсера — **payload JSON-API** (dict), а не HTML. Функции чистые, без сети,
без глобального состояния (контракт снят с реального ответа, см. §3):

- `catalog_grid(payload: dict) -> dict` — найти **виджет каталога магазина**: `tileGridDesktop`,
  у плиток есть `brandLogo`, `header is None`. Виджет рекомендаций («Возможно, вам понравится»,
  30 чужих плиток) отбрасывается целиком — фильтровать по `sellerId` нельзя, его в плитке нет;
- `parse_tile(tile: dict) -> ProductPrice` — цена из `mainState[].priceV2` по `textStyle`
  (`PRICE` / `ORIGINAL_PRICE`), стиль из `priceV2.priceStyle.styleType`, имя из `textDS`
  с `testInfo.automatizationId == "tile-name"`, ссылка из `action.link` (отбросить `?at=`);
- `parse_catalog(payload: dict) -> list[ProductPrice]` — плитки → модели;
- `is_end_of_catalog(payload: dict) -> bool` — грид пришёл с `error == "no data"`;
- исключение `ParseError` — если виджета каталога нет и это не конец каталога.

Тесты (`test_parser.py`, только фикстуры):

1. `catalog_page_1.json` → **8** товаров, у каждого непустые `sku`/`url`/`name`, `price is not None`;
2. разбор совпадает с `catalog_page_1.expected.json` поле в поле (эталон, а не «примерно»);
3. `price_style == "CARD_PRICE"`, `price_original is None` — как в реальном каталоге;
4. рекомендательный грид (30 плиток, молоко/куртки) **не попадает** в результат;
5. подмена структуры (пустой dict / нет `widgetStates`) → `ParseError`, а не пустой список;
6. `catalog_page_empty.json` → `is_end_of_catalog`, но не `ParseError`;
7. `sku` из URL совпадает с полем плитки; `?at=`-трекинг вырезан из `url`;
8. нормализация: `"1 234,50 ₽"` (в т.ч. `\u2009`) → `Decimal("1234.50")`;
9. плитка без `priceV2` → `price is None`, `in_stock is None`, товар не теряется
   (кейс синтетический: в реальных фикстурах не встретился).

**Проверка:** `pytest -q tests/test_parser.py`.
**Критерий готовности:** все тесты зелёные, ни один тест не ходит в сеть. Прототип
`prototype/poc_ozon_prices.py --offline` уже проходит сверку с эталоном — **PASS**.

### Шаг 3 — `fetcher.py` (транспорт за единым протоколом)

- `class PageFetcher(Protocol): async def fetch(self, page: int) -> dict` — воркер не знает про транспорт,
- `CtxRequestFetcher` — **основной**: `BrowserContext.request.get(API, params=...)` с cookie из
  `storage_state.json`, без открытия страницы (проверено: 200, 0.2–0.6 с),
- `InPageFetchFetcher` — fallback: `page.evaluate(fetch)` внутри открытой страницы (тоже 200),
- `HttpFetcher` (`httpx`) — **не реализуем в v1**: проверено, что с теми же cookie отдаёт
  `403 fab_*`; оставляем заметку, чтобы не «оптимизировать» транспорт обратно,
- `SessionExpired` → один перепрогрев через `bootstrap.ensure_session()` → один повтор,
- `Blocked` / капча → отдельное исключение, решение о паузах принимает воркер,
- задержка между запросами: `REQUEST_DELAY` (2.5 с) + jitter; jitter отключается флагом
  (для детерминированных тестов).

**Проверка:** `python scripts/smoke_browser.py` → итоговый URL, число плиток, транспорт
(`ctx_request` / `in_page_fetch`).
**Критерий готовности:** одна реальная страница получена через `PageFetcher`; оба транспорта
удовлетворяют одному протоколу и подменяются в тестах.

### Шаг 4 — `catalog_urls.py` (чистые) + постраничный обход

`catalog_urls.py` — только чистые функции, без I/O:

- `build_page_url(page: int) -> str` — URL страницы API (`...?url=/seller/knig-gora/products/?page=N`),
- `sku_from_url(url: str) -> str` / `canonical_product_url(link: str) -> str` — из `action.link`
  (`/product/<slug>-<sku>/?at=…`) в `https://www.ozon.ru/product/<slug>-<sku>/`.

Обход страниц живёт в `price_worker.py` и принимает `PageFetcher` (инъекция), поэтому
тестируется без сети: `collect_pages(fetcher, limit_pages, limit_items)`:

- дедупликация по `sku` в рамках запуска (`seen: set[str]`),
- ранний выход: `is_end_of_catalog(payload)` — **единственный** надёжный сигнал конца
  (`nextPage` пагинатора есть всегда, по нему останавливаться нельзя),
- остановка при достижении **любого** из лимитов: `--pages` или `--limit`; `--limit`
  режет внутри страницы (страница = **8** товаров).

Тесты (`test_catalog_urls.py`, фикстуры + фейковый fetcher):

1. URL для `page=1/2/10`;
2. `canonical_product_url` вырезает `?at=`, `sku_from_url` работает на slug-варианте и `/product/<sku>/`;
3. дедупликация SKU, повторяющихся на двух страницах (`catalog_page_1/2`);
4. остановка на `catalog_page_empty.json` (`error: "no data"`);
5. `--limit 5` при 8 плитках → ровно 5 товаров и один запрос;
6. `--pages 1 --limit 100` → один запрос, не два.

**Проверка:** `pytest -q tests/test_catalog_urls.py`.
**Критерий готовности:** пагинация покрыта тестами, лимиты работают, сеть не нужна.

### Шаг 5 — `price_worker.py`

- единица работы — **страница каталога**, а не SKU: одна страница = один запрос + до 8 моделей;
- `--concurrency` (по умолчанию 1; без прокси не поднимать выше 2–3): параллельные `ctx.request`
  работают (3 запроса — 0.42 с), но IP один, поэтому лимит остаётся;
- ретраи: экспоненциальный `backoff` с jitter, 3 попытки, учёт `Retry-After`;
- обработка блокировки: `Blocked` → пауза (60 с) → повтор; 3 подряд → остановка
  с внятной ошибкой, а не бесконечный цикл;
- чекпоинт: `progress.jsonl` — страница + список `sku` на странице; `--resume` пропускает
  обработанные страницы и `sku`; битая последняя строка игнорируется;
- запись результата в `data/prices_<timestamp>.jsonl` — **одна строка = один товар**,
  пишем целой строкой + `flush` (без полустрок при падении);
- SIGINT: закрыть файлы и остановиться, чекпоинт остаётся валидным;
- логи в stderr: `ok/no_price/blocked/retry` + итоговая сводка через `report.py`.

Тесты (`test_checkpoint.py`, без сети, воркер вызывается с фейковым `PageFetcher`):

1. первый запуск обрабатывает 3 товара → в `progress.jsonl` 3 записи;
2. `--resume` при готовых 3 из 5 → запрашиваются только 2;
3. падение на 2-м товаре → 1-й сохранён, повтор не выполняется;
4. `Blocked` три раза подряд → воркер останавливается с ошибкой;
5. битая последняя строка `progress.jsonl` не ломает `--resume`;
6. `--limit` и `--pages` вместе → отсечение по первому достигнутому.

**Проверка:** `pytest -q tests/test_checkpoint.py`.
**Критерий готовности:** возобновление доказано тестом, «зависаний» нет.

### Шаг 6 — хранение среза — **JSON вместо PostgreSQL (18.11.2026)**

Решение: БД не используем. Состав:

- `prototype/out/prices.jsonl` — по строке на товар, поля из §4 (без `prev_price`
  и `price_changed_at`: уведомления не нужны);
- `data/prices_<YYYY-MM-DD_HHMM>.json` — тот же срез + метаданные прогона
  (`started_at`, `pages`, `total`, `with_price`, `no_price`, `transport`);
- `--dry-run`: собрали, распарсили, посчитали — ничего не записали (единая семантика флага);
- запись целыми строками с `flush`, повторный прогон перезаписывает `latest.json`.

SQL-вариант (`ozon_prices` + `ozon_runs`, upsert с `prev_price`) остаётся в §4 как отложенный:
он проверен на PostgreSQL 18 и понадобится, только если вернёмся к БД и сравнению цен.

**Проверка:** `python3 prototype/poc_ozon_prices.py --pages 1 --limit 8 --out prototype/out/prices.jsonl`
→ файл валиден, число строк совпадает с числом товаров.

### Шаг 7 — `cli.py` + `report.py` + первый реальный прогон

- `python -m ozon_price_scraper --pages 2 --limit 30 --out data/prices.jsonl [--dry-run] [--resume] [--log-level INFO]`,
- порядок: `ensure_session` → постраничный сбор → парсинг → JSONL → `upsert` + `record_run`,
- `--out` по умолчанию `data/prices_<timestamp>.jsonl`; при явном `--out` — ровно этот путь
  (второго имени файла не появляется),
- `report.py`: `всего/с ценой/без цены/заблокировано/сколько цен изменилось`, время работы;
  человекочитаемо в stderr + JSON (`data/report_<timestamp>.json`) для сверки,
- README: установка, `playwright install chromium`, `.env`, примеры запуска, «Responsible use»,
- прогон на 20–50 товарах, сверка 3–5 цен глазами в браузере, результат — в отчёт,
- полный каталог: 109 страниц, ≈5 мин при паузе 2.5 с; конец каталога проверен на 110-й странице
  (`error: "no data"`). Это уже не «срез 20–50», а полный обход — включать осознанно.

**Критерий готовности:** получен файл с ценами (JSON) и фото в `images/`; цифры и картинки
сверены с сайтом.

### Шаг 8 — фото галерей — **выполняется** (`prototype/download_images.py`)

- обход каталога (109 страниц) → список книг;
- на каждую книгу — запрос карточки (`entrypoint-api.bx/page/json/v2?url=/product/<slug>-<sku>/`),
  из виджета `webGallery` берутся `images[].src`; если галереи нет — fallback `coverImage`,
  если и его нет — обложка из каталога (`tileImage`);
- скачивание с `ir.ozone.ru` (публичный CDN, без авторизации), `--img-workers 3`;
- раскладка: `shops/<магазин>/<slug>/01.jpg…`, `info.json` на книгу, `index.json`/`index.csv` на всё;
- идемпотентность: готовые книги и файлы пропускаются (`--no-resume` — перекачать);
- пауза между карточками — `--delay` (по умолчанию 2.5 с): 869 карточек ≈ 40–50 мин.

**Проверка:** `ls images | wc -l`,
`python3 -c "import json;d=json.load(open('images/index.json'));print(d['books_count'], d['photos_count'])"`,
`file images/*/01.jpg` → JPEG.

## 7. Тесты: требования

- детерминированные: без сети, без `sleep`, без случайности (jitter отключается флагом в тестах);
- изолированные: каждый тест готовит и убирает свои данные (tmp_path, транзакция с откатом);
- парсер тестируется только на фикстурах **JSON-API** (не HTML — меньше объём, меньше гниения);
- воркер — с фейковым `PageFetcher`, сеть не нужна ни одному тесту;
- сторадж — на реальном PostgreSQL (`pytest-postgresql`/`testcontainers`), иначе `skip`
  по отсутствию `DATABASE_URL`;
- фикстуры сопровождаются эталоном (`*.expected.json`), чтобы тест ловил изменение разбора,
  а не «примерное совпадение»; фикстуры **уже реальные** (сняты на шаге 0) и лежат в `fixtures/`;
- `prototype/poc_ozon_prices.py --offline` — референсная проверка контракта: если она перестала
  проходить, сломан либо парсер, либо договор с Ozon (это первое, что запускаем при «сломалось»);
- обязательный кейс «контракт изменился» → `ParseError`, а не тихий пустой результат;
- запуск: `pytest -q` (полный набор), вывод показывается фактически, не пересказом;
- `ruff check .` + `mypy ozon_price_scraper` — те же команды в CI (`.github/workflows/ci.yml`).

## 8. Риски и как их снимаем

| Риск | Вероятность | Что делаем |
|---|---|---|
| Капча/челлендж | средняя | **проверено:** headless-Chromium проходит (18.11.2026); persistent-профиль + `storage_state.json`; headed — fallback |
| Антибот режет не-браузерный HTTP (`fab`) | высокая | транспорт только `BrowserContext.request` / in-page `fetch`; `httpx` не используем (проверено: `403 fab_*`) |
| Детект headless при смене защиты | средняя | сейчас не детектится; при изменении — persistent-профиль, отключение признаков автоматизации, headed-режим |
| `storage_state.json` протух | высокая (часы–сутки) | `SessionExpired` → перепрогрев → один повтор; проверка сессии перед обходом |
| Блокировка по IP при полном обходе | средняя | пауза 2.5 с + jitter, `--concurrency ≤ 2`, полный обход (109 запросов) — только осознанно |
| `?page=N` перестанет работать | низкая | **проверено, что работает**; fallback — `nextPage`/`layout_page_index` из пагинатора |
| Смена контракта JSON-API | высокая (раз в месяцы) | `ParseError` + тест на «сломанную» фикстуру, разбор изолирован в `parser.py`, вёрстку не парсим |
| Чужой грид в том же ответе (рекомендации) | **высокая (уже случилось)** | берём виджет каталога по правилу `brandLogo + header is None`; 30 рекомендательных плиток отбрасываются целиком |
| `CARD_PRICE` ≠ «обычная цена» | высокая (всегда) | фиксируем `price_style`; в отчётах пишем «цена с Ozon Картой», не «цена» |
| Товар без цены | низкая (не встречен) | `price = NULL`, `in_stock = NULL`, счётчик `no_price`; правило ждёт реального кейса |
| **18+ карточка** | **высокая (уже случилось)** | Ozon отдаёт только `userAdultModal`; ставим `is_adult_confirmed=true` + `adult_user_birthdate=1990-01-01` (`ensure_adult`), затем `repair.py` |
| **Блокировка по IP** | **высокая (случилось 19.11.2026)** | 403 «Похоже, нет соединения» на все запросы; ждать 30–60 мин, сменить сеть/IP, `--refresh`, снизить темп (`--delay 5 --card-concurrency 1`) |
| Каталог меняется между прогонами | высокая | снимок `_books.json` на старте; при необходимости `--refresh-catalog`; число книг проверять живым обходом |
| Характеристик/размеров нет у части карточек | высокая | это данные продавца, а не баг; размеры лежат в `characteristics["Размеры, мм"]`, вес — `["Вес товара, г"]` |
| ToS Ozon запрещает авт. сбор | — | личное использование, пауза между запросами, без перепродажи данных, раздел «Responsible use» в README |

Ограничение, которое принимаем: по умолчанию v1 собирает **срез 20–50 товаров** (см. §1).
Полный обход (869 товаров, 109 запросов, ≈5 мин) технически проходит одним IP — но это уже
нагрузка на чужой сервис, поэтому включается осознанно, а не «по умолчанию».

Фактически на 19.11.2026 полные каталоги пяти магазинов (1 902 книги) скачаны; после одного
из полных обходов Ozon ответил IP-блоком `403` — порядок восстановления в §0.

## 9. Команды проверки по шагам

> **Актуальные команды — в §0** (19.11.2026). Блок ниже — исторический план 18.11.2026:
> пакета `ozon_price_scraper`, pytest, CI и PostgreSQL в реализации нет.

```bash
# шаг 0 (офлайн-проверка контракта на фикстурах, без сети) -> PASS
python3 prototype/poc_ozon_prices.py --offline

# шаг 1
pytest -q
python -c "import ozon_price_scraper; print('ok')"
python -m ozon_price_scraper --help

# шаг 2
pytest -q tests/test_parser.py

# шаг 0.5/3 (smoke, реальная сеть — 1 страница)
python scripts/smoke_browser.py

# шаг 4
pytest -q tests/test_catalog_urls.py

# шаг 5
pytest -q tests/test_checkpoint.py

# шаг 6
pytest -q tests/test_storage.py

# шаг 7
ruff check . && mypy ozon_price_scraper
pytest -q
python -m ozon_price_scraper --pages 1 --limit 20 --dry-run
python -m ozon_price_scraper --pages 1 --limit 20 --out data/prices.jsonl
psql "$DATABASE_URL" -c "SELECT count(*), count(price), count(*) FILTER (WHERE price IS NULL) FROM ozon_prices;"
psql "$DATABASE_URL" -c "SELECT count(*) FROM ozon_prices WHERE price_changed_at IS NOT NULL;"
```

## 10. Порядок коммитов (предлагаемые имена)

1. `docs: план парсера цен магазина knig-gora на Ozon (+ ревью)`
2. `chore: скелет репозитория ozon-price-scraper (pyproject, gitignore, CI)`
3. `feat: bootstrap браузерной сессии Playwright с прогревом и детектом блокировки`
4. `feat: парсер JSON-выдачи с тестами на фикстурах`
5. `feat: транспорт fetch (ctx.request + in-page) за единым протоколом`
6. `feat: пагинация каталога и дедупликация по sku`
7. `feat: page-worker с ретраями, чекпоинтами и корректной остановкой`
8. `feat: сохранение среза цен в PostgreSQL (upsert + prev_price + runs)`
9. `feat: CLI, сводка прогона и первый реальный прогон`

## 11. Решения по открытым вопросам (были вопросы — стали решения)

> Исторические решения 18.11.2026. Фактически БД нет (JSONL + `info.json`), магазинов пять,
> обход полный — см. §0.

| Вопрос | Решение |
|---|---|
| PostgreSQL обязателен или достаточно JSONL/CSV? | JSONL — обязательный промежуточный артефакт; PostgreSQL — да, v1 пишет туда (`ozon_prices` + `ozon_runs`). CSV — только ручной экспорт, если понадобится |
| Нужен ли фильтр по разделам магазина? | В v1 фильтров нет: берём виджет каталога магазина (8 товаров/страница); рекомендательные гриды в том же ответе отбрасываются целиком |
| Хранить ли «цену без Ozon Карты»? | Нет: Ozon её не отдаёт в каталоге (проверено). Храним `price` + `price_style` (`CARD_PRICE`) и пишем в отчётах «цена с Ozon Картой» |
| Полный каталог или срез? | По умолчанию срез (`--limit`), полный обход 869 товаров — отдельным осознанным запуском (`--pages 0/full`) |
| Лимит первого прогона: 20 или 50? | 50, но значение — параметр CLI (`--limit`), а не константа в коде и тестах |

Нерешённого, блокирующего шаг 1, не осталось.

## 12. Журнал шагов

| Шаг | Статус | Дата | Заметка |
|---|---|---|---|
| План | готов | 18.11.2026 | разведка curl: 307-цикл, нужен Playwright |
| Ревью | готово | 18.11.2026 | гибридный транспорт, JSON-фикстуры, `prev_price`/`run_id`, закрыты §11; DDL и upsert прогнаны на временном PostgreSQL 18 |
| 0 | **готов** | 18.11.2026 | `entrypoint-api.bx` подтверждён; `httpx` → `403 fab_*`, работает `ctx.request`; 8 товаров/стр., 869 товаров, конец = `error: "no data"`; фикстуры сняты |
| 0.5 | прототип | 18.11.2026 | headless-Chromium проходит челлендж; bootstrap 4.8 с; сессия переиспользуется без `goto` |
| 8 | **готов** | 18.11.2026 | 848 книг, 5 084 фото (2,3 ГБ), в среднем 6 фото и 12,8 характеристик; 49 карточек пустые (`stale`: товар снят, в каталоге остался) |
| config | **готов** | 19.11.2026 | `prototype/shop_config.py` — SLUG/TITLE/SELLER_ID/пути в одном файле; полный URL в SLUG отсекается `_validate_slug()` |
| 18+ | **готов** | 19.11.2026 | `userAdultModal` → `ADULT_COOKIES` + `ensure_adult`; 35 карточек «Старой книги» и 78 в остальных магазинах дозаполнены |
| repair | **готов** | 19.11.2026 | `repair.py --out/--delay`; во всех 5 магазинах **0** карточек без характеристик |
| каталоги | **готов** | 19.11.2026 | 1 902 книги, 10 424 фото: 848 + 332 + 138 + 130 + 454 |
| IP-блок | инцидент | 19.11.2026 | 403 «Похоже, нет соединения» после полного обхода; помогли пауза/смена сети/`--refresh`, данные добраны |
| 1–7 | не начаты | — | ждут шага 1 (кроме 2–5, реализованных в `poc_ozon_prices.py`) |

### Итоги тестовых прогонов 18.11.2026

| Прогон | Команда | Результат |
|---|---|---|
| Офлайн-контракт | `poc_ozon_prices.py --offline` | **PASS**: 8/8 товаров совпали с эталоном, overlap страниц 0, конец каталога распознан |
| Живой E2E | `poc_ozon_prices.py --pages 3 --limit 24 --out ...` | **24 товара с ценами**, 6.5 с, JSONL валиден, `sku` в URL совпадает |
| Конец каталога | запрос `page=110` | `error: "no data"`, 200, 0.55 с |
| Параллельность | 3 запроса одновременно | 0.42 с суммарно, ошибок нет |
| Полнота каталога | бинарный поиск последней страницы | последняя с товарами — 109 (5 товаров), 110 — пусто ⇒ **869 товаров** |
| SQL | DDL + upsert на PostgreSQL 18 | `prev_price`/`price_changed_at`/`NULL`/`CHECK` — все инварианты выполняются |
| Фото + обогащение | `download_images.py --refresh-info --card-concurrency 3` | **848 книг, 5 084 фото, 2,3 ГБ** за ~30 мин; 3–10 фото на книгу |
| Характеристики (фрагмент 2) | `layout_container=pdpPage2column&layout_page_index=2` | в среднем **12,8** (макс 17); ISBN есть у **788** книг из 848 |
| Ремонт | `repair.py` | 3 книги с гонкой по фото исправлены; 49 карточек пустые (товар снят, помечены `stale`) |

### Итоги 19.11.2026

| Проверка | Команда / действие | Результат |
|---|---|---|
| Офлайн-контракт | `python3 prototype/poc_ozon_prices.py --offline` | **PASS** |
| Тесты | `python3 -m unittest discover -s tests -v` | **9 тестов OK**, сеть не используется |
| Переключение магазина | правка только `prototype/shop_config.py` | 5 магазинов, у каждого своя папка и `prices_<slug>.jsonl` |
| 18+ карточки | `ensure_adult` + `repair.py` | 113 карточек получили характеристики: 35 + 49 + 17 + 7 + 5 |
| Полнота | подсчёт `info.json` | **1 902 книги, 0 без характеристик** |
| Фото | суммы `index.json` | **10 424 фото**, перекачки не было |
| IP-блок | 403 «Похоже, нет соединения» | восстановлено паузой/сменой сети/`--refresh`, данные добраны |



