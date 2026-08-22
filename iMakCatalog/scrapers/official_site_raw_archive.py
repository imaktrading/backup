#!/usr/bin/env python3
"""公式サイト由来の行の生データを残す (bandai API を持たない分).

2026-08-23。8/22 に API 由来 (12,043件) は保存済み。残っているのは
**各ゲームの公式サイトから取り込んだ行** で、API の URL を持たないため保存できていない。

    ワンピ    2,449行 → 公式カードリストは **1ページに複数カード**。ユニークURL 55本だけ
    DBSCG     1,591行 → 1カード1ページ
    ガンダム    819行 → 1カード1ページ
                          合計 約2,460リクエスト (1.5秒間隔で約1時間)

保存先は API 分と同じ `_raw/<category>/`。衝突しないよう `site_` を頭に付ける。
**DB は書き換えない。保管だけ。**

実行:
  python scrapers/official_site_raw_archive.py --limit 5      # 動作確認
  python scrapers/official_site_raw_archive.py --all
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sqlite3
import sys
import time
import urllib.request
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scrapers"))
import api  # noqa: E402
import _raw_store  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
SLEEP = 1.5
CATS = ("one_piece_tcg", "dragonball_scg", "gundam_tcg", "pokemon_tcg")


def key_for(url: str) -> str:
    """URL から保存キーを作る (同じページは1本にまとめる)."""
    m = re.search(r"series=(\w+)", url)
    if m:
        return "site_series_" + m.group(1)
    m = re.search(r"card_no=([\w\-]+)(?:&p=(\w+))?", url)
    if m:
        return "site_" + m.group(1) + (("_" + m.group(2)) if m.group(2) else "")
    m = re.search(r"detailSearch=([\w\-]+)", url)
    if m:
        return "site_" + m.group(1)
    return "site_" + hashlib.sha1(url.encode()).hexdigest()[:16]


def run(cat: str, limit: int | None) -> Counter:
    db = sqlite3.connect(api._DB_PATH, timeout=60)
    urls = []
    seen = set()
    for (u,) in db.execute("SELECT DISTINCT source_url FROM products WHERE category=? "
                           "AND source_url IS NOT NULL AND source_url NOT LIKE '%api.bandai%' "
                           "AND source_url LIKE 'http%' "
                           # PSA の cert ページは公式カード情報ではない (403 も返る)
                           "AND source_url NOT LIKE '%psacard.com%'", (cat,)):
        k = key_for(u)
        if k in seen:
            continue
        seen.add(k)
        urls.append((k, u))
    db.close()
    if limit:
        urls = urls[:limit]
    n = Counter()
    t0 = time.time()
    for i, (k, u) in enumerate(urls, 1):
        if _raw_store.have(cat, k):
            n["手元に有り"] += 1
            continue
        try:
            h = urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=30)\
                .read().decode("utf-8", "replace")
        except Exception as e:
            n["失敗"] += 1
            if n["失敗"] <= 3:
                print(f"   ! {u}: {e}", flush=True)
            continue
        _raw_store.save(cat, k, h, u)
        n["保存"] += 1
        time.sleep(SLEEP)
        if i % 100 == 0:
            print(f"  {cat} {i}/{len(urls)} {dict(n)} 経過{(time.time()-t0)/60:.1f}分", flush=True)
    print(f"[{cat}] 対象 {len(urls)} URL → {dict(n)}", flush=True)
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--category", choices=CATS)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--limit", type=int)
    args = ap.parse_args()
    cats = CATS if args.all else ([args.category] if args.category else [])
    if not cats:
        ap.error("--category か --all が要る")
    total = Counter()
    for c in cats:
        total += run(c, args.limit)
    print("合計:", dict(total))


if __name__ == "__main__":
    main()
