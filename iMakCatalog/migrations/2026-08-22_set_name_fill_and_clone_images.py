#!/usr/bin/env python3
"""set_name が NULL の行に公式名を入れる + クローン行の画像を公式から入れる.

2026-08-22。HQ 依頼 (`2026-08-22_hq_cards_that_can_never_reach_listing.md`)。

## 1. set_name が NULL (1,893行 / MBG-* 22枚を含む)
`set_name` は **社内の突き合わせ用**。eBay に出すのは `specs.set_name_ebay` の方
(決定表 `_contract_aspects.yaml`)。eBay 値が無い弾は set_name も NULL のままで、
PSA ラベルとの突き合わせが失敗していた (cert 136425633 が誤検出)。
→ **eBay 値が無いときは公式の日本語セット名を入れる**。1つの規則で例外を作らない。

## 2. クローン行の画像 (one_piece 3件)
公式ページは画像を遅延読込していて `src="/images/cardlist/dummy.gif"`、
実URLは **`data-src`** 側にある。取り込みがここを踏んでいなかった。
公式ページから `data-src` を取って入れる。**親カードの画像をコピーしない**
(刷り違いに別の絵が入ると目視照合が誤る)。

実行:
  python migrations/2026-08-22_set_name_fill_and_clone_images.py           # dry-run
  python migrations/2026-08-22_set_name_fill_and_clone_images.py --commit
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import urllib.request
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import api  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

NOW = datetime.now().isoformat(timespec="seconds")
UA = {"User-Agent": "Mozilla/5.0"}


def official_image(url: str, card_no: str) -> str | None:
    """公式カードリストの data-src から画像URLを取る."""
    try:
        h = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30)\
            .read().decode("utf-8", "replace")
    except Exception as e:
        print(f"   ! {url}: {e}")
        return None
    m = re.search(r'data-src="([^"]*' + re.escape(card_no) + r'[^"]*\.png)[^"]*"', h)
    if not m:
        return None
    p = m.group(1).lstrip(".")
    return "https://www.onepiece-cardgame.com" + (p if p.startswith("/") else "/" + p)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()
    db = sqlite3.connect(api._DB_PATH, timeout=120)
    db.row_factory = sqlite3.Row
    n, updates_sn, updates_img = Counter(), [], []

    # 1. set_name NULL → 公式名
    for r in db.execute("SELECT id, category, set_name_official, specs FROM products "
                        "WHERE set_name IS NULL AND set_name_official IS NOT NULL"):
        s = json.loads(r["specs"] or "{}")
        if (s.get("set_name_ebay") or "").strip():
            continue                       # eBay 値が在るなら set_name もそちらが入るはず
        n[f"set_name 補完: {r['category']}"] += 1
        updates_sn.append((r["set_name_official"], NOW, r["id"]))

    # 2. クローン行の画像
    for r in db.execute("SELECT id, product_id, source_url, images FROM products "
                        "WHERE category='one_piece_tcg' AND source LIKE '%clone_%'"):
        if r["images"] and r["images"] != "[]":
            continue
        base = str(r["product_id"]).split("_")[0]
        if "onepiece-cardgame.com" not in (r["source_url"] or ""):
            n[f"公式ページが無い: {r['product_id']}"] += 1
            continue
        url = official_image(r["source_url"], base)
        if not url:
            n[f"公式に画像が見つからず: {r['product_id']}"] += 1
            continue
        print(f"   {r['product_id']} -> {url}")
        n["画像を入れた"] += 1
        updates_img.append((json.dumps([url], ensure_ascii=False), NOW, r["id"]))

    print("=== %s ===" % ("APPLY" if args.commit else "DRY-RUN"))
    print("  ", dict(n))
    if args.commit:
        if updates_sn:
            db.executemany("UPDATE products SET set_name=?, updated_at=? WHERE id=?", updates_sn)
        if updates_img:
            db.executemany("UPDATE products SET images=?, updated_at=? WHERE id=?", updates_img)
        db.commit()
        print(f"[OK] set_name {len(updates_sn)}行 / 画像 {len(updates_img)}行")
    else:
        print("(dry-run — --commit で適用)")
    db.close()


if __name__ == "__main__":
    main()
