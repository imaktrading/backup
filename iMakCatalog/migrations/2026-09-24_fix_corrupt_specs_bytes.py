# -*- coding: utf-8 -*-
"""specs / images の JSON が壊れている行を直す (2026-09-24).

`images` 版 (`2026-09-24_fix_corrupt_image_bytes.py`) と同じ事故。
実測で見つかったのは3種:

    `"` -> `*`            GA-100LT-1A  (`ebay_search_volume*:null`)
    `"` -> 0x02           GD05-019     (`....png\x02,`)
    文字列の中に CR       GA-100PC-7A2 (`"water_resistance:_200\r"`) ← これは化けではなく取り込み時の混入

直し方はどれも **元の1文字に戻す / 余分な制御文字を外す** だけ。直した後 json.loads が通ることを確かめ、
通らないものは触らず報告する (推測で書き換えない)。
"""
import json
import re
import sqlite3
import sys

db = sqlite3.connect("C:/dev/iMak_data/catalog/products.sqlite", timeout=120)
commit = "--commit" in sys.argv
n = bad = 0
for pid, sp, im in db.execute("SELECT product_id, specs, images FROM products").fetchall():
    for col, v in (("specs", sp), ("images", im)):
        if v is None:
            continue
        try:
            json.loads(v)
            continue
        except json.JSONDecodeError:
            pass
        fixed = (v.replace('*:null', '":null').replace('\x02,', '",')
                  .replace('\r', '').replace('\n', ''))
        fixed = re.sub(r'[\x00-\x1f]', '', fixed)
        try:
            json.loads(fixed)
        except Exception as e:
            bad += 1
            print(f"  ✗ {pid} {col}: 直せない ({e}) → 手で見る")
            continue
        n += 1
        print(f"  {pid} {col} 修復")
        if commit:
            db.execute(f"UPDATE products SET {col}=? WHERE product_id=?", (fixed, pid))
if commit:
    db.commit()
print(f"{n}行 修復 / {bad}行 手つかず", "適用" if commit else "dry-run")
