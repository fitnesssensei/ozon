#!/usr/bin/env python3
"""Ремонт: добирает отсутствующие характеристики и недокачанные фото.

Запуск: python3 prototype/repair.py [--out ПАПКА] [--concurrency 3] [--delay 0.4]
По умолчанию ПАПКА = IMAGES_DIR из shop_config.py.
"""
import argparse
import asyncio
import json
import pathlib
import sys

from playwright.async_api import async_playwright

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from download_images import (API, ROOT, STATE, UA, download_one, ensure_adult,  # noqa: E402
                             ensure_state, ext_of, parse_chars, parse_gallery,
                             parse_short_chars, rebuild_from_disk)


def plan(root: pathlib.Path):
    jobs = []
    for folder in sorted(p for p in root.iterdir() if p.is_dir()):
        info_file = folder / "info.json"
        if not info_file.exists():
            continue
        try:
            info = json.loads(info_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        files = {p.name for p in folder.iterdir()
                 if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")}
        listed = {p["file"] for p in (info.get("photos") or [])}
        need_chars = not info.get("characteristics")
        need_photos = (not info.get("photos")) or bool(files - listed) or bool(listed - files)
        if need_chars or need_photos:
            jobs.append({"folder": folder, "info": info, "need_chars": need_chars,
                         "need_photos": need_photos})
    return jobs


async def repair_one(ctx, job: dict, sem: asyncio.Semaphore, total: int, idx: int,
                     delay: float = 0.4):
    async with sem:
        folder, info = job["folder"], job["info"]
        path = info["url"].replace("https://www.ozon.ru", "")
        done = []

        r = await ctx.request.get(API, params={"url": path}, timeout=40000)
        payload = json.loads(await r.body()) if r.status == 200 else {}

        if job["need_photos"] and payload:
            srcs = parse_gallery(payload)
            width = max(2, len(str(len(srcs))))
            photos = []
            for i, src in enumerate(srcs, 1):
                dest = folder / f"{i:0{width}d}{ext_of(src)}"
                _s, size, err = download_one(src, dest)
                if not err:
                    photos.append({"file": dest.name, "src": src, "bytes": size})
            if photos:
                info["photos"] = photos
                done.append(f"photos={len(photos)}")

        if job["need_chars"]:
            chars: dict = {}
            r2 = await ctx.request.get(
                API, params={"url": path + "?layout_container=pdpPage2column&layout_page_index=2"},
                timeout=40000)
            if r2.status == 200:
                chars = parse_chars(json.loads(await r2.body()))
            if not chars and payload:
                chars = parse_short_chars(payload)
            if chars:
                info["characteristics"] = chars
                done.append(f"chars={len(chars)}")

        tmp = folder / "info.json.tmp"
        tmp.write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.rename(folder / "info.json")
        print(f"[{idx}/{total}] {info['sku']}: {' '.join(done) or 'без изменений'}", flush=True)
        await asyncio.sleep(delay)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT), help="папка магазина (по умолчанию IMAGES_DIR)")
    ap.add_argument("--concurrency", type=int, default=3)
    ap.add_argument("--delay", type=float, default=0.4, help="пауза между карточками, сек")
    args = ap.parse_args()
    root = pathlib.Path(args.out).resolve()

    await ensure_state()
    jobs = plan(root)
    print(f"папка: {root}")
    print(f"к ремонту: {len(jobs)} книг "
          f"(без характеристик: {sum(j['need_chars'] for j in jobs)}, "
          f"с неполными фото: {sum(j['need_photos'] for j in jobs)})", flush=True)
    if not jobs:
        return 0

    sem = asyncio.Semaphore(max(1, args.concurrency))
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        ctx = await b.new_context(user_agent=UA, locale="ru-RU", storage_state=str(STATE))
        await ensure_adult(ctx)
        await asyncio.gather(*(repair_one(ctx, j, sem, len(jobs), i, args.delay)
                               for i, j in enumerate(jobs, 1)))
        await b.close()

    left = plan(root)
    print(f"\nосталось проблемных: {len(left)} "
          f"(без характеристик: {sum(j['need_chars'] for j in left)})")
    rebuild_from_disk(root)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
