#!/usr/bin/env python3
"""必須項目 Game が空欄の行を埋める (2,835行).

2026-08-22。eBay の aspect を自分で取得して突合したら発覚。

## 何が問題か
`Game` は **eBay の CCG Individual Cards (183454) で唯一の必須項目**。
scraper が stamp し忘れた行は空欄のまま出品に流れていた:

    pokemon 804 / one_piece 96 / gundam 407 / dragonball 1,528  = 2,835行

## 直し方
category から一意に決まる値なので、`api.derive_game_ebay()` で埋める。推測ではない。
読み出し側 (`_row_to_dict`) にも同じ導出を入れたので、**今後 scraper が忘れても空欄にならない**。
本 migration は stored 側を揃えるだけ (契約 v1.2 §1-5 の restamp 方式)。

★`Gundam Card Game` は eBay の Game 一覧 (168値) に無い。
  一覧にあるのは `Gundam War TCG` = 1990年代の別ゲームで、寄せてはいけない。
  他セラーも自由入力で `Gundam Card Game` を出しており、それに揃える (ユーザー確認 2026-08-22)。
  絞り込みには乗らないが、必須項目は埋まる。

実行:
  python migrations/2026-08-22_game_ebay_backfill.py           # dry-run
  python migrations/2026-08-22_game_ebay_backfill.py --commit
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

NOW = datetime.now().isoformat()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()
    db = sqlite3.connect(api._DB_PATH)
    db.row_factory = sqlite3.Row

    print("=== Game (必須項目) の空欄を埋める (%s) ===" % ("APPLY" if args.commit else "DRY-RUN"))
    hits, updates, skipped = Counter(), [], Counter()
    for r in db.execute("SELECT id, category, specs FROM products WHERE specs IS NOT NULL"):
        s = json.loads(r["specs"] or "{}")
        if (s.get("game_ebay") or "").strip():
            continue
        g = api.derive_game_ebay(r["category"])
        if not g:
            skipped[r["category"]] += 1      # 未知 category は触らない (fail-closed)
            continue
        hits[(r["category"], g)] += 1
        s["game_ebay"] = g
        s["game_ebay_source"] = "derive_from_category_20260822"
        updates.append((json.dumps(s, ensure_ascii=False), NOW, r["id"]))

    for (cat, g), n in hits.most_common():
        print("  %-16s -> %-30r %6d" % (cat, g, n))
    if skipped:
        print("\n  category が未知で触らなかった行:")
        for cat, n in skipped.most_common():
            print("    %-16s %d" % (cat, n))
    print("\n合計 %d 行" % len(updates))

    if args.commit and updates:
        db.executemany("UPDATE products SET specs=?, updated_at=? WHERE id=?", updates)
        db.commit()
        print("[OK] 適用")
    elif not args.commit:
        print("(dry-run — --commit で適用)")
    db.close()


if __name__ == "__main__":
    main()
