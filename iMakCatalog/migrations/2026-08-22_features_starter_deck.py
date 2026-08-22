#!/usr/bin/env python3
"""Features に 'Starter Deck' を足す (収録商品がスターターデッキの行).

2026-08-22。HQ から「ポケモンの features_ebay が 9%」と指摘。
足せるのは **商品の種類から確実に言えるもの**だけ。

  収録弾が スターターセット / スタートデッキ / はじめてセット / 対戦スターター
    → eBay Features の 'Starter Deck' (一覧に在る値)

## 足さないもの (理由)
- **`Holo` / `Reverse Holo`** … eBay の Features 39値に**無い**。これは `Finish` の値で、
  Finish は現物を見ないと決まらないので出さないと決めている (CLAUDE.md)
- **レアリティからの Full Art / Alternative Art 推定** … AR/SAR/CHR/CSR は
  全面イラストだが、**カタログのデータでは裏が取れない**。誤ると商品説明の誤りになる。
  出品の正確性原則 (推測で埋めない) に従い空欄のままにする

実行:
  python migrations/2026-08-22_features_starter_deck.py           # dry-run
  python migrations/2026-08-22_features_starter_deck.py --commit
"""
from __future__ import annotations

import argparse
import json
import re
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
RE_STARTER = re.compile(r"スターターセット|スタートデッキ|はじめてセット|対戦スターター")
CATS = ("pokemon_tcg", "one_piece_tcg", "dragonball_scg", "gundam_tcg")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()
    db = sqlite3.connect(api._DB_PATH)
    db.row_factory = sqlite3.Row
    n, updates = Counter(), []
    for r in db.execute("SELECT id, category, set_name_official, specs FROM products "
                        "WHERE category IN (%s)" % ",".join("?" * len(CATS)), CATS):
        if not (r["set_name_official"] and RE_STARTER.search(r["set_name_official"])):
            continue
        s = json.loads(r["specs"] or "{}")
        cur = s.get("features_ebay") or []
        cur = list(cur) if isinstance(cur, list) else [cur]
        if "Starter Deck" in cur:
            continue
        cur.append("Starter Deck")
        s["features_ebay"] = cur
        s["features_ebay_source"] = "starter_deck_from_set_20260822"
        n[r["category"]] += 1
        updates.append((json.dumps(s, ensure_ascii=False), NOW, r["id"]))
    print("=== Features に Starter Deck (%s) ===" % ("APPLY" if args.commit else "DRY-RUN"))
    print("  足す %d 行  %s" % (len(updates), dict(n)))
    if args.commit and updates:
        db.executemany("UPDATE products SET specs=?, updated_at=? WHERE id=?", updates)
        db.commit()
        print("[OK] 適用 %d 行" % len(updates))
    elif not args.commit:
        print("(dry-run — --commit で適用)")
    db.close()


if __name__ == "__main__":
    main()
