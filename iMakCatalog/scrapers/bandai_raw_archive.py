#!/usr/bin/env python3
"""ワンピ / ドラゴンボール / ガンダムの生データ (API JSON) を残す.

2026-08-22。ポケモンと同じ考え方 — **次に別の項目が要るとき取り直さないため**。
この3ゲームは bandai-tcg-plus の API で取っており、返ってくる JSON には
card_config (Color / Power / Cost / Trait / AP / HP …) が丸ごと入っている。
今 DB に入れていない項目も JSON には在るので、生のまま残す。

- 保存先: `C:/dev/iMak_data/catalog/_raw/<category>/<card_id>.json.gz`
- 既に生データが有るカードは **取りに行かない** (--refetch で強制)
- **DB は書き換えない**。これは保管だけのツール

実行:
  python scrapers/bandai_raw_archive.py --category one_piece_tcg --limit 20
  python scrapers/bandai_raw_archive.py --all
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scrapers"))
import api  # noqa: E402
import _raw_store  # noqa: E402
import one_piece_tcg as opcg  # noqa: E402  (session / SLEEP を借りる)
import json as _json

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

CATS = ("one_piece_tcg", "dragonball_scg", "gundam_tcg")
ID_RE = re.compile(r"/api/user/card/(\d+)")


def run(cat: str, limit: int | None, refetch: bool) -> Counter:
    db = sqlite3.connect(api._DB_PATH)
    rows = db.execute("SELECT source_url FROM products WHERE category=? AND "
                      "source_url LIKE '%api/user/card/%'", (cat,)).fetchall()
    ids = []
    seen = set()
    for (u,) in rows:
        m = ID_RE.search(u or "")
        if m and m.group(1) not in seen:
            seen.add(m.group(1))
            ids.append((m.group(1), u))
    if limit:
        ids = ids[:limit]
    n = Counter()
    t0 = time.time()
    for i, (cid, url) in enumerate(ids, 1):
        if not refetch and _raw_store.have(cat, cid, ext="json"):
            n["手元に有り"] += 1
            continue
        try:
            r = opcg._session.get(url, timeout=30)
        except Exception as e:
            n["失敗"] += 1
            if n["失敗"] <= 3:
                print(f"   ! {url} {e}")
            continue
        if r.status_code != 200 or not r.text:
            n["失敗"] += 1
            if n["失敗"] <= 3:
                print(f"   ! {url} HTTP {r.status_code}")
            continue
        _raw_store.save(cat, cid, r.text, url, ext="json")
        n["保存"] += 1
        time.sleep(opcg.SLEEP_BETWEEN_CALLS)
        if i % 200 == 0:
            print(f"  {cat} {i}/{len(ids)}  {dict(n)}  経過{(time.time()-t0)/60:.1f}分", flush=True)
    db.close()
    print(f"[{cat}] 対象 {len(ids)} 枚 → {dict(n)}")
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--category", choices=CATS)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--refetch", action="store_true")
    args = ap.parse_args()
    cats = CATS if args.all else ([args.category] if args.category else [])
    if not cats:
        ap.error("--category か --all が要る")
    total = Counter()
    for c in cats:
        total += run(c, args.limit, args.refetch)
    print("合計:", dict(total))


if __name__ == "__main__":
    main()
