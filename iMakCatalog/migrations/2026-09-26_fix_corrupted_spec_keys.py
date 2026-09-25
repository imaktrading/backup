# -*- coding: utf-8 -*-
"""化けた specs のキー名を直す (2026-09-26).

依頼: `requests/2026-09-26_products_db_corrupted_rows.md` の続き。
JSON としては読めるが **キー名の1文字が化けている**行があった。値の化けより見つけにくく、
`test_raw_to_ebay_fields_20260906` が1件だけ赤になって初めて気づいた。

    DPt4-B-040   `p_ebay        -> hp_ebay
    SVI-040      card_type_eba9 -> card_type_ebay
    SV5a-031     typd_jp        -> type_jp
    E422559-000  compgsition    -> composition

直す条件 (推測で書き換えない):
  - 正しいキーが **同じカテゴリの他の行で普通に使われている**
  - 化けたキーは その行にしか無い (1文字違い)
  - 正しいキーが その行にまだ無い (上書きしない)

実行: python migrations/2026-09-26_fix_corrupted_spec_keys.py [--commit]
"""
from __future__ import annotations

import json
import sqlite3
import sys

DB = "C:/dev/iMak_data/catalog/products.sqlite"
commit = "--commit" in sys.argv

FIX = {                      # 化けたキー -> 正しいキー
    "`p_ebay": "hp_ebay",
    "card_type_eba9": "card_type_ebay",
    "typd_jp": "type_jp",
    "compgsition": "composition",
}

db = sqlite3.connect(DB, timeout=300)
n = 0
for pid, cat, sp in db.execute("SELECT product_id, category, specs FROM products").fetchall():
    try:
        d = json.loads(sp or "{}")
    except Exception:
        continue
    hit = [k for k in d if k in FIX]
    if not hit:
        continue
    for k in hit:
        good = FIX[k]
        cnt = db.execute(
            "SELECT count(*) FROM products WHERE category=? AND json_extract(specs, ?) IS NOT NULL",
            (cat, f"$.{good}")).fetchone()[0]
        if cnt < 10:
            print(f"  ✗ {pid}: {good} が同じカテゴリで {cnt}行しか使われていない → 触らない")
            continue
        if good in d:
            # 仕上げ (finish_ingest) が正しいキーを入れ直した後の行。化けた方は残骸なので消す。
            if d[good] == d[k]:
                d.pop(k)
                n += 1
                print(f"  {pid} ({cat}): {k} を消す ({good} は既に正しい値)")
            else:
                print(f"  ✗ {pid}: {good} が在って値も違う ({d[good]!r} vs {d[k]!r}) → 手で見る")
            continue
        d[good] = d.pop(k)
        n += 1
        print(f"  {pid} ({cat}): {k} -> {good} = {d[good]!r}")
    if commit:
        db.execute("UPDATE products SET specs=? WHERE product_id=?",
                   (json.dumps(d, ensure_ascii=False), pid))
if commit:
    db.commit()
print(f"{n}件", "適用" if commit else "dry-run")
