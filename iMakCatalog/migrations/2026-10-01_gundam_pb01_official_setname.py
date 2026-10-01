# -*- coding: utf-8 -*-
"""PB01 (プレミアムグッズセット ガンダムW) の正しい行を公式どおりにする (2026-10-01).

依頼: `requests/2026-09-30_gundam_pb01_resolver_returns_imageless_clone.md`

## 判定: ① カタログのデータが誤り

2026-10-01 に公式を**その場で取り直して**確かめた
(`https://www.gundam-gcg.com/jp/cards/detail.php?detailSearch=<pid>` の「入手情報」欄):

    ST02-010_p4   入手情報 = プレミアムグッズセット-新機動戦記ガンダムW-[PB01]   (レアリティ C+)
    GD01-100_p4   入手情報 = プレミアムグッズセット-新機動戦記ガンダムW-[PB01]   (レアリティ U+)

つまり **PB01 の行は公式に在る** (`_p4`、画像つき)。それなのに 2026-07 に
`ST02-010_PB01` / `GD01-100_PB01` という **画像なしの複製行**を別に作り、
照合関数がそちらを返していた。出品くんは毎回 NO-IMAGE で落としていた (4日/6回)。

さらに `_p4` 側の `set_name_official` は公式の入手情報ではなく
汎用の `限定商品収録カード` が入っていた (取り込みが欄を取り違えている)。

## やること

  1. `_p4` 2行の `set_name_official` を公式の入手情報に直す
  2. 複製行 `*_PB01` 2行を消す (公式に対応する行が在るので持つ理由が無い)

★`set_name_ebay` は変わらない。`ebay_filter_map/gundam.yaml` で
  `限定商品収録カード` も `プレミアムグッズセット-...[PB01]` も `Promo Cards` に寄る。

実行: python migrations/2026-10-01_gundam_pb01_official_setname.py [--commit]
"""
from __future__ import annotations

import json
import sqlite3
import sys

DB = "C:/dev/iMak_data/catalog/products.sqlite"
OFFICIAL = "プレミアムグッズセット-新機動戦記ガンダムW-[PB01]"
FIX = ["ST02-010_p4", "GD01-100_p4"]
DROP = ["ST02-010_PB01", "GD01-100_PB01"]

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def main() -> None:
    commit = "--commit" in sys.argv
    c = sqlite3.connect(DB, timeout=120)
    print(f"=== PB01 の行を公式どおりに ({'APPLY' if commit else 'DRY-RUN'}) ===")
    for pid in FIX:
        row = c.execute("SELECT set_name_official, images FROM products "
                        "WHERE category='gundam_tcg' AND product_id=?", (pid,)).fetchone()
        if not row:
            print(f"  ✗ {pid}: 行が無い")
            continue
        imgs = len(json.loads(row[1] or "[]"))
        print(f"  {pid}: {row[0]!r} -> {OFFICIAL!r} (画像 {imgs}枚)")
        if commit:
            c.execute("UPDATE products SET set_name_official=? "
                      "WHERE category='gundam_tcg' AND product_id=?", (OFFICIAL, pid))
    for pid in DROP:
        n = c.execute("SELECT count(*) FROM products WHERE category='gundam_tcg' "
                      "AND product_id=?", (pid,)).fetchone()[0]
        print(f"  複製行を消す {pid}: {n}行")
        if commit:
            c.execute("DELETE FROM products WHERE category='gundam_tcg' AND product_id=?", (pid,))
    if commit:
        c.commit()
        print("適用した")
    else:
        print("(dry-run — --commit で適用)")
    c.close()


if __name__ == "__main__":
    main()
