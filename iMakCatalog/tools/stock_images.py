# -*- coding: utf-8 -*-
"""どの経路で手に入れた UT の画像も **倉庫に残す** (2026-09-13 新設・ユーザー指示「画像が肝」).

公式から消えると画像は二度と取れない。だから出所を問わず、見つけた画像は倉庫に置く。

    _raw/fashion_press/img/<記事ID>/     Fashion Press の写真   (fashion_press_images.py)
    _raw/uniqlo_ut/ (image_urls)         公式 CDN の画像URL     (catalog の値)
    _raw/uniqlo_ut/thumb/                公式 CDN の縮小版
    _raw/uniqlo_blog/img/<記事ID>/       ブログ記事の画像       ← この道具
    _raw/user_ut_photos/<フォルダ名>/     ユーザーが手で集めた画像 ← この道具 (複製して保全)

★中身 (名前・素材・色) の出所は公式のまま。ここで残すのは **画像とその出所** だけ。

実行:
    python tools/stock_images.py --blog          ブログ記事の画像
    python tools/stock_images.py --user-folder   手元フォルダの複製
    python tools/stock_images.py                 両方
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import gzip
import json
import re
import shutil
import sys
import time
import urllib.request
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

DATA = Path("C:/dev/iMak_data/catalog")
BLOG_RAW = DATA / "_raw/uniqlo_blog"
BLOG_IMG = BLOG_RAW / "img"
USER_SRC = Path("C:/Users/imax2/OneDrive/デスクトップ/ebay/出品関係/UNIQLO UT")
USER_DST = DATA / "_raw/user_ut_photos"
INDEX = DATA / "image_stock_index.json"
UA = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/140.0 Safari/537.36")}
IMG = re.compile(r'<img[^>]+src="(https?://[^"]+\.(?:jpg|jpeg|png|webp))"', re.I)
EXT = {".jpg", ".jpeg", ".png", ".webp", ".avif", ".gif"}


def fetch(job: tuple[Path, str]) -> str:
    p, url = job
    if p.exists() and p.stat().st_size > 0:
        return "skip"
    for i in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as r:
                data = r.read()
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)                 # ★1枚ずつ保存
            time.sleep(0.3)
            return "ok"
        except Exception:
            time.sleep(3 * (i + 1))
    return "err"


def blog_images() -> dict:
    jobs, by_post = [], {}
    for f in sorted(BLOG_RAW.glob("post_*.html.gz")):
        nid = f.name[len("post_"):-len(".html.gz")]
        h = gzip.open(f, "rb").read().decode("utf-8", "ignore")
        urls = [u for u in dict.fromkeys(IMG.findall(h))
                if "livedoor" in u or "uniqlo" in u or "blogimg" in u]
        by_post[nid] = urls
        for u in urls:
            jobs.append((BLOG_IMG / nid / u.rsplit("/", 1)[-1].split("?")[0], u))
    print(f"=== ブログの画像 — 記事 {len(by_post)}本 / 画像 {len(jobs):,}枚 ===", flush=True)
    stat: dict[str, int] = {}
    with cf.ThreadPoolExecutor(max_workers=4) as ex:
        for i, r in enumerate(ex.map(fetch, jobs), 1):
            stat[r] = stat.get(r, 0) + 1
            if i % 200 == 0:
                print(f"    {i:,}/{len(jobs):,} {stat}", flush=True)
    print(f"    {stat}")
    return {"blog_posts": {k: len(v) for k, v in by_post.items()}, "blog_stat": stat}


def user_folder() -> dict:
    if not USER_SRC.exists():
        print("  手元フォルダが見つかりません")
        return {}
    n = skip = 0
    for f in USER_SRC.rglob("*"):
        if f.is_file() and f.suffix.lower() in EXT:
            dst = USER_DST / f.parent.name / f.name
            if dst.exists() and dst.stat().st_size == f.stat().st_size:
                skip += 1
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dst)
            n += 1
    print(f"=== 手元フォルダの複製 — 複製 {n}枚 / 既に在る {skip}枚 → {USER_DST}")
    return {"user_copied": n, "user_skipped": skip}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--blog", action="store_true")
    ap.add_argument("--user-folder", action="store_true")
    a = ap.parse_args()
    both = not (a.blog or a.user_folder)
    info = {}
    if a.blog or both:
        info.update(blog_images())
    if a.user_folder or both:
        info.update(user_folder())
    INDEX.write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")
    total = sum(1 for _ in (DATA / "_raw").rglob("*") if _.suffix.lower() in EXT)
    print(f"\n  倉庫の画像 合計 {total:,}枚")


if __name__ == "__main__":
    main()
