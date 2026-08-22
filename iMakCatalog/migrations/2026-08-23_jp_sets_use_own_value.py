#!/usr/bin/env python3
"""日本語版セットは **自分のセットの値** を使う (例外を廃止).

2026-08-23 ユーザー確定「シンプルが一番」。ルールはこれだけ:

    ① eBay にそのセットの値があれば、それをそのまま使う
    ② 無ければ、日本語セット名の英語表記を自由入力で入れる (空欄にしない)
    ③ **英語版の別セット名は使わない**

これまで 2026-08-18 の裁定で 14セット (1,361行) が英語版セットの値を持っていた
(例: 拡張パック「漆黒のガイスト」 -> `Swsh06: Sword & Shield - Chilling Reign`)。
実測すると **14セットとも eBay に日本語版セットの値が在った**ので、例外は不要だった。

    漆黒のガイスト   -> S6k: Jet-Black Spirit
    白銀のランス     -> S6h: Silver Lance
    ロストアビス     -> S11: Lost Abyss
    パラダイムトリガー -> S12: Paradigm Trigger   ほか10セット

## なぜ通常の restamp では直らないか
旧値も eBay の一覧に在る値なので、格下げ禁止ガードが素通りさせる。
「別セットの実在値」は §0 の弾コード検知でしか気づけない (Swsh は裁定として除外していた)。

実行:
  python migrations/2026-08-23_jp_sets_use_own_value.py           # dry-run
  python migrations/2026-08-23_jp_sets_use_own_value.py --commit
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
SOURCE = "jp_set_own_value_20260823"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()
    db = sqlite3.connect(api._DB_PATH, timeout=120)
    db.row_factory = sqlite3.Row
    pairs, updates = Counter(), []
    for r in db.execute("SELECT id, product_id, set_name_official, specs FROM products "
                        "WHERE category='pokemon_tcg'"):
        s = json.loads(r["specs"] or "{}")
        cur = s.get("set_name_ebay") or ""
        if not cur.upper().startswith("SWSH"):
            continue
        new = api.derive_set_name_ebay("pokemon_tcg", r["set_name_official"], r["product_id"])
        if not new or new == cur:
            continue
        pairs[(cur, new)] += 1
        s["set_name_ebay"] = new
        s["set_name_ebay_source"] = SOURCE
        updates.append((json.dumps(s, ensure_ascii=False), NOW, r["id"]))
    print("=== 日本語版セットを自分の値へ (%s) ===" % ("APPLY" if args.commit else "DRY-RUN"))
    print("  直す %d 行 / %d 組" % (len(updates), len(pairs)))
    for (a, b), n in pairs.most_common(20):
        print(f"    {a[:40]:40s} -> {b:30s} {n}")
    if args.commit and updates:
        db.executemany("UPDATE products SET specs=?, updated_at=? WHERE id=?", updates)
        db.commit()
        print("[OK] 適用 %d 行" % len(updates))
    elif not args.commit:
        print("(dry-run — --commit で適用)")
    db.close()


if __name__ == "__main__":
    main()
