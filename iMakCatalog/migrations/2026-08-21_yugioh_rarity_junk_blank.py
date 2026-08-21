#!/usr/bin/env python3
"""レアリティでない値が C:Rarity に出ているのを空欄にする (遊戯王 118行).

2026-08-21。eBay の Rarity 一覧 (57値) を自分で取得して全カテゴリを突合したら発覚。

## 何が出ていたか
`ygoprodeck_full_expansion` が取り込んだ生値を、遊戯王だけ **passthrough** していたため、
レアリティですらない文字列がそのまま C:Rarity に流れていた:

    New 56 / '2' 29 / '3' 23 / European & Oceanian debut 6 /
    force-SMW 1 / Reprint 1 / Oceanian debut 1 / European debut 1     = 118行

'2' や 'European debut' は**発売地域や版の注記**であって、レアリティではない。

## なぜ passthrough していたか
監査 (tools/set_name_integrity_audit.py) が「遊戯王は生値が既に英語 canonical なので
passthrough が正」として rarity チェックから**除外**していた。
その前提が、こういう非レアリティ値まで通してしまっていた。

## 何をするか
**空欄にする。値を推測で埋めない** (グローバル規約「間違った内容で出品しない」)。
eBay の Rarity は FREE_TEXT なので、空欄でも出品は通る (絞り込みに乗らないだけ)。
誤ったレアリティで出すより空欄の方が安全。

★これは「eBay の一覧に無い」から消すのではない。
  `Short Print` や `Duel Terminal Normal Parallel Rare` は一覧に無いが**実在するレアリティ**
  なので残す。消すのは**レアリティという語ですらないもの**だけ。

実行:
  python migrations/2026-08-21_yugioh_rarity_junk_blank.py           # dry-run
  python migrations/2026-08-21_yugioh_rarity_junk_blank.py --commit
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

# レアリティではない値 (実測して1つずつ確認したもの)
JUNK = {
    "New": "版の注記。レアリティではない",
    "2": "数字だけ。レアリティではない",
    "3": "数字だけ。レアリティではない",
    "European debut": "発売地域の注記",
    "Oceanian debut": "発売地域の注記",
    "European & Oceanian debut": "発売地域の注記",
    "Reprint": "再録の注記。レアリティではない",
    "force-SMW": "取り込み時のゴミ",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()
    db = sqlite3.connect(api._DB_PATH)
    db.row_factory = sqlite3.Row

    print("=== レアリティでない値を空欄化 (%s) ===" % ("APPLY" if args.commit else "DRY-RUN"))
    hits, updates = Counter(), []
    for r in db.execute("SELECT id, category, product_id, specs FROM products "
                        "WHERE specs IS NOT NULL"):
        s = json.loads(r["specs"] or "{}")
        v = s.get("rarity_ebay")
        if v not in JUNK:
            continue
        hits[(r["category"], v)] += 1
        s["rarity_ebay"] = ""
        s["rarity_ebay_status"] = "not_a_rarity_blanked_20260821"
        s["rarity_ebay_status_note"] = (
            "取り込み元の生値がレアリティではなかった (%s)。推測で埋めず空欄にする。"
            "eBay の Rarity は FREE_TEXT なので空欄でも出品は通る。" % JUNK[v])
        updates.append((json.dumps(s, ensure_ascii=False), NOW, r["id"]))

    for (cat, v), n in hits.most_common():
        print("  %-14s %-30r %4d行   ← %s" % (cat, v, n, JUNK[v]))
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
