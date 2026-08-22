#!/usr/bin/env python3
"""features_ebay をリストに直す + Country of Origin を入れる.

2026-08-22。決定表を作った流れで実データを検算したら **こちらの不具合**が出た。

## 1. features_ebay が「カンマで繋いだ1つの文字列」になっていた (1,185行)
    'Promo, Alternative Art' (962行) / 'Alternative Art, Starter Deck' (223行)
eBay の Features は **MULTI** (複数値可) なので、1つの値として送ると
`Promo, Alternative Art` という**存在しない値**を送ることになる。リストに直す。

## 2. Country of Origin (eBay 244値・選択式) に `Japan` が在る
日本版の刷り (language=Japanese) は `Japan` で確定。出品側が固定値で入れていたが、
言語はカタログが持っているのでカタログ側で持つ (判断を出品側に残さない)。

実行:
  python migrations/2026-08-22_features_list_and_country.py           # dry-run
  python migrations/2026-08-22_features_list_and_country.py --commit
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
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
MASTER = Path(r"C:\dev\iMak_data\catalog\_input\ebay_aspects_183454_latest.json")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()
    A = json.loads(MASTER.read_text(encoding="utf-8"))["aspects"]
    FE, CO = set(A["Features"]["all"]), set(A["Country of Origin"]["all"])
    assert "Japan" in CO
    db = sqlite3.connect(api._DB_PATH, timeout=120)
    db.row_factory = sqlite3.Row
    n, updates = Counter(), []
    for r in db.execute("SELECT id, specs FROM products"):
        s = json.loads(r["specs"] or "{}")
        touched = False
        v = s.get("features_ebay")
        if isinstance(v, str) and "," in v:
            parts = [p.strip() for p in v.split(",") if p.strip()]
            if all(p in FE for p in parts):          # 全部が eBay の値の時だけ分割
                s["features_ebay"] = parts
                n["features をリストに"] += 1
                touched = True
            else:
                n["分割できず (要確認)"] += 1
        if not (s.get("country_of_origin_ebay") or "").strip():
            if (s.get("language") or "") == "Japanese":
                s["country_of_origin_ebay"] = "Japan"
                n["Country of Origin=Japan"] += 1
                touched = True
        if touched:
            updates.append((json.dumps(s, ensure_ascii=False), NOW, r["id"]))
    print("=== %s ===" % ("APPLY" if args.commit else "DRY-RUN"))
    print("  %d 行  %s" % (len(updates), dict(n)))
    if args.commit and updates:
        db.executemany("UPDATE products SET specs=?, updated_at=? WHERE id=?", updates)
        db.commit()
        print("[OK] 適用 %d 行" % len(updates))
    elif not args.commit:
        print("(dry-run — --commit で適用)")
    db.close()


if __name__ == "__main__":
    main()
