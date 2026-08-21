#!/usr/bin/env python3
"""ポケモンのプロモ弾番号を変換表に足す (S-P / SV-P / BWP).

2026-08-22。eBay の値リストと突合して、**正体が確定したものだけ**足す。

## 経緯
`X-P` 形式の弾番号 (SM-P / S-P / SV-P) は、product_id を最初のハイフンで切ると
'SM' / 'S' / 'SV' になり、変換表に在っても引けなかった。
api 側の切り出しを直したので (2026-08-22)、あとは行が無いものを足す。

## 足すもの (eBay の値リストに実在することを確認済)
    S-P  -> 'S-P: Sword & Shield Promos'   316行  (product_id S-P-001…)
    BWP  -> 'BW-P Promotional cards'       229行  (product_id BWP-001…)
    SV-P -> 'Sv-P Promotional Cards'       273行  (product_id SV-P-001…)

eBay の日本版プロモは `<era>-P` 系で揃っている
(ADV-P / BW-P / DPt-P / PCG-P / Sv-P / Sm-P / S-P)。上の3つはこの系列に収まる。

## 足さないもの (正体が確定できない / eBay に無い)
    XYP  277行  eBay に XY-P 系が**無い** → 据え置き
    SVM  175行  公式セット名が空でカード名も手がかりにならず、どの商品か確定できない
    SVD  139行  同上
    SMH  131行  同上

**推測で寄せない。** 'Sm Promo' を 'Sm' に寄せる、のような候補が自動照合で出たが、
プロモ 352件を通常セットに入れることになるので採らなかった。

実行:
  python migrations/2026-08-22_pokemon_promo_setcode.py           # dry-run
  python migrations/2026-08-22_pokemon_promo_setcode.py --commit
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
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
MASTER = Path(r"C:\dev\iMak_data\catalog\_input\ebay_aspects_183454_latest.json")
VERIFY = "ebay_aspects_183454_20260821+promo_setcode_20260822"

ADD = [
    ("S-P",  "S-P: Sword & Shield Promos"),
    ("BWP",  "BW-P Promotional cards"),
    ("SV-P", "Sv-P Promotional Cards"),
    # 2026-07-31 に「master に canonical 無し」として空欄化した3セット。
    # 当時は全ゲーム混在の旧マスタしか無く見つけられなかっただけで、
    # 2026-08-21 取得の Game 別マスタには **在る** (実測)。192行が埋まる。
    ("SM5S", "Sm5s: Ultra Sun"),
    ("SM5M", "Sm5m: Ultra Moon"),
    ("SM5p", "Sm5+: Ultra Force"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()

    pool = set(json.loads(MASTER.read_text(encoding="utf-8"))
               ["aspects"]["Set"]["by_game"]["Pokémon TCG"])
    db = sqlite3.connect(api._DB_PATH)
    db.row_factory = sqlite3.Row
    print("=== プロモ弾番号の追加 (%s) ===" % ("APPLY" if args.commit else "DRY-RUN"))

    n_add = 0
    for code, ebay in ADD:
        if ebay not in pool:
            print("  ✗ %-6s %r が eBay の一覧に無い → skip (fail-closed)" % (code, ebay))
            continue
        rows = db.execute("SELECT COUNT(*) FROM products WHERE category='pokemon_tcg' "
                          "AND product_id LIKE ?", (code + "-%",)).fetchone()[0]
        if rows == 0:
            print("  ✗ %-6s 該当カードが0件 → skip" % code)
            continue
        exists = db.execute("SELECT 1 FROM ebay_filter_map WHERE category='pokemon_tcg' "
                            "AND field='set_code' AND source_value=?", (code,)).fetchone()
        if exists:
            print("  - %-6s 既に在る" % code)
            continue
        print("  + %-6s -> %-34r  対象 %d行" % (code, ebay, rows))
        if args.commit:
            db.execute("INSERT INTO ebay_filter_map (category, field, source_value, ebay_value, "
                       "note, created_at, status, verified_at, verify_source) "
                       "VALUES (?,?,?,?,?,?,?,?,?)",
                       ("pokemon_tcg", "set_code", code, ebay,
                        "2026-08-22 プロモ弾番号 (eBay の <era>-P 系に一致)",
                        NOW, "A", NOW, VERIFY))
        n_add += 1

    print("\n追加 %d 行" % n_add)
    if args.commit:
        db.commit()
        print("[OK] 適用 — 続けて tools/restamp_set_name_ebay.py で products を焼き直すこと")
    else:
        print("(dry-run — --commit で適用)")
    db.close()


if __name__ == "__main__":
    main()
