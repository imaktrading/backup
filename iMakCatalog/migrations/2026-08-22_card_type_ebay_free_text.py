#!/usr/bin/env python3
"""card_type_ebay を残りのゲームでも埋める (自由入力なので eBay 一覧外でよい).

2026-08-22。HQ 指摘「DBSCG だけ 2% は天井ではなく作業残では」→ **指摘が正しい**。

前回こちらは「eBay の Card Type 74値に無いので天井」と答えたが**誤り**だった。
eBay の Card Type は **FREE_TEXT** (自由入力) で、ワンピは 'Character'、ガンダムは
'Unit' と、一覧に無い値を既に入れている。DBSCG だけ入れていなかった。

規約 (Set の裁定と同じ考え方):
  ① eBay の一覧に在る値 → それを入れる
  ② 無い → 公式の呼び方を英語表記で入れる (空欄にしない)
  ③ 別ゲームの値で代用する → 禁止

日本語の生値は英語に直す (`キャラクター` -> `Character`)。
生値そのものが無い行 (DBSCG 2,754 / ガンダム 87) は**空欄のまま** = 元データが無い。

実行:
  python migrations/2026-08-22_card_type_ebay_free_text.py           # dry-run
  python migrations/2026-08-22_card_type_ebay_free_text.py --commit
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
MAP = {
    "BATTLE": "Battle", "EXTRA": "Extra", "LEADER": "Leader",
    "ENERGY MARKER": "Energy Marker", "UNISON": "Unison",
    "キャラクター": "Character", "イベント": "Event", "リーダー": "Leader",
    "ステージ": "Stage", "ドン!!カード": "DON!! Card", "DON!!カード": "DON!! Card",
    "Character": "Character", "Event": "Event", "Leader": "Leader",
    "Stage": "Stage", "DON!! Card": "DON!! Card",
    "UNIT": "Unit", "PILOT": "Pilot", "COMMAND": "Command", "BASE": "Base",
    "RESOURCE": "Resource", "UNIT TOKEN": "Unit Token", "UNIT・TOKEN": "Unit Token",
    "EX BASE": "EX Base", "EX RESOURCE": "EX Resource", "TOKEN": "Token",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()
    db = sqlite3.connect(api._DB_PATH)
    db.row_factory = sqlite3.Row
    n, skip, updates = Counter(), Counter(), []
    for r in db.execute("SELECT id, category, specs FROM products WHERE category IN "
                        "('one_piece_tcg','dragonball_scg','gundam_tcg')"):
        s = json.loads(r["specs"] or "{}")
        if (s.get("card_type_ebay") or "").strip():
            continue
        raw = str(s.get("card_type") or "").strip()
        if not raw:
            skip["生値が無い"] += 1
            continue
        v = MAP.get(raw)
        if not v:
            skip[f"表に無い: {raw}"] += 1
            continue
        s["card_type_ebay"] = v
        s["card_type_ebay_source"] = "free_text_20260822"
        n[f"{r['category']}:{v}"] += 1
        updates.append((json.dumps(s, ensure_ascii=False), NOW, r["id"]))
    print("=== card_type_ebay (自由入力) %s ===" % ("APPLY" if args.commit else "DRY-RUN"))
    print("  埋める %d 行" % len(updates))
    for k, v in n.most_common():
        print(f"    {k:34s} {v}")
    print("  見送り: %s" % skip.most_common(5))
    if args.commit and updates:
        db.executemany("UPDATE products SET specs=?, updated_at=? WHERE id=?", updates)
        db.commit()
        print("[OK] 適用 %d 行" % len(updates))
    elif not args.commit:
        print("(dry-run — --commit で適用)")
    db.close()


if __name__ == "__main__":
    main()
