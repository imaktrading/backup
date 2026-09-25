# -*- coding: utf-8 -*-
"""JSON が壊れている行をバックアップの値で戻す (2026-09-26).

依頼: `requests/2026-09-26_products_db_corrupted_rows.md` の続き。
`2026-09-26_restore_corrupted_rows.py` で UTF-8 として読めない分と索引は直ったが、
**1文字だけ化けて JSON として読めない行**が7件残っていた (例 `"card_number_total": b102"`、
`"finish*: ""`、`"hp_eb\x01y"`)。どれも 9/24 05:00 のバックアップでは正常。

推測で書き換えない: **バックアップの値が JSON として読めて、更新日が同じ行だけ**戻す。
更新日が違う行は触らず一覧に出す (後から手で見る)。

実行: python migrations/2026-09-26_restore_broken_json_from_backup.py [--commit]
"""
from __future__ import annotations

import json
import sqlite3
import sys

DB = "C:/dev/iMak_data/catalog/products.sqlite"
BK = "C:/tmp/bk/iMak_daily_20260924_0500/products.sqlite"
commit = "--commit" in sys.argv

db = sqlite3.connect(DB, timeout=300)
bk = sqlite3.connect(BK)
fixed = skipped = 0
for pid, sp, im, up in db.execute(
        "SELECT product_id, specs, images, updated_at FROM products").fetchall():
    for col, v in (("specs", sp), ("images", im)):
        try:
            json.loads(v or "[]")
            continue
        except Exception as e:
            err = str(e)[:40]
        row = bk.execute(f"SELECT {col}, updated_at FROM products WHERE product_id=?",
                         (pid,)).fetchone()
        if not row or row[0] is None:
            print(f"  ✗ {pid} {col}: バックアップに無い ({err})")
            skipped += 1
            continue
        try:
            json.loads(row[0])
        except Exception:
            print(f"  ✗ {pid} {col}: バックアップ側も壊れている ({err})")
            skipped += 1
            continue
        if row[1] != up:
            print(f"  ✗ {pid} {col}: 更新日が違う (現在 {up} / backup {row[1]}) → 手で見る")
            skipped += 1
            continue
        print(f"  {pid} {col} 戻す ({err})")
        fixed += 1
        if commit:
            db.execute(f"UPDATE products SET {col}=? WHERE product_id=?", (row[0], pid))
if commit:
    db.commit()
print(f"{fixed}行 戻す / {skipped}行 手つかず", "適用" if commit else "dry-run")
