#!/usr/bin/env python3
"""Собирает images/index.html из images/index.json (статические ссылки, без сервера).

Запуск:  python3 prototype/make_gallery_html.py
Файл можно открыть локально или выложить на сайт вместе с папкой images/.
"""
import html
import json

from shop_config import IMAGES_DIR, SELLER_ID, TITLE

ROOT = IMAGES_DIR

PAGE = """<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<title>{title} — фото товаров</title>
<style>
 body{{font-family:-apple-system,Segoe UI,Roboto,sans-serif;margin:24px;background:#f6f7f9;color:#111}}
 h1{{margin:0 0 4px;font-size:22px}} .sub{{color:#666;margin-bottom:20px}}
 .grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:16px}}
 .card{{background:#fff;border-radius:10px;padding:10px;box-shadow:0 1px 3px rgba(0,0,0,.08)}}
 .thumbs{{display:flex;gap:6px;overflow-x:auto;margin-bottom:8px}}
 .thumbs img{{height:130px;border-radius:6px;background:#eee;object-fit:cover}}
 .name{{font-size:13px;line-height:1.3;margin-bottom:6px}}
 .price{{font-weight:600;color:#c2185b}} .meta{{font-size:12px;color:#777}}
 a{{color:#0059c8;text-decoration:none}} a:hover{{text-decoration:underline}}
</style></head><body>
<h1>{title} — фото товаров</h1>
<div class="sub">{books} книг, {photos} фото · собрано {when} · источник: Ozon (seller {seller_id})</div>
<div class="grid">
{cards}
</div></body></html>
"""

CARD = """<div class="card">
 <div class="thumbs">{thumbs}</div>
 <div class="name"><a href="{url}" target="_blank" rel="noreferrer">{name}</a></div>
 <div class="price">{price} ₽</div>
 <div class="meta">{sku} · фото: {count}</div>
</div>"""


def main() -> int:
    data = json.loads((ROOT / "index.json").read_text(encoding="utf-8"))
    cards = []
    for book in data["books"]:
        photos = book.get("photos") or []
        thumbs = "".join(
            f'<img loading="lazy" src="{html.escape(book["folder"])}/{html.escape(p["file"])}" alt="">'
            for p in photos[:8]
        ) or '<span class="meta">нет фото</span>'
        cards.append(CARD.format(
            thumbs=thumbs,
            url=html.escape(book.get("url") or ""),
            name=html.escape((book.get("name") or "")[:120]),
            price=html.escape(book.get("price") or ""),
            sku=html.escape(book["sku"]),
            count=len(photos),
        ))
    out = PAGE.format(books=data["books_count"], photos=data["photos_count"],
                      when=html.escape(data.get("generated_at", "")), cards="\n".join(cards),
                      title=html.escape(TITLE), seller_id=SELLER_ID)
    (ROOT / "index.html").write_text(out, encoding="utf-8")
    print(f"готово: {ROOT / 'index.html'} ({len(cards)} книг, {data['photos_count']} фото)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
