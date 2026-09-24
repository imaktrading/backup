# -*- coding: utf-8 -*-
"""画像欄に紛れた壊れた1バイトを直す (2026-09-24).

2行だけ、images の中の1文字が別のバイトに化けていた (sqlite の integrity_check は ok、
1バイトだけの化けなので書き込み時の事故と思われる)。放っておくと JSON として読めず、
その category を見る監査・テストが丸ごと落ちる (実際に 14件 落ちた)。

    uniqlo_ut  E437857-000          `"` (0x22) -> 0xa2
    yugioh_tcg 22219822_FLOD-EN007  `a` (0x61) -> 0xa1

直し方は **化けたバイトを元の文字に戻すだけ** (URL の中身は前後から一意に決まる)。
直した後 json.loads が通ることを確かめる。
"""
import json
import sqlite3
import sys

db = sqlite3.connect("C:/dev/iMak_data/catalog/products.sqlite", timeout=120)
db.text_factory = bytes
commit = "--commit" in sys.argv
n = 0
for pid, im in db.execute("SELECT product_id, images FROM products").fetchall():
    if im is None:
        continue
    try:
        im.decode("utf-8")
        continue
    except UnicodeDecodeError:
        pass
    fixed = im.replace(b"\xa2", b'"').replace(b"c\xa1rds", b"cards")
    try:
        json.loads(fixed.decode("utf-8"))
    except Exception as e:
        print(f"  ✗ {pid.decode('utf-8', 'replace')}: 直せない ({e}) → 手で見る")
        continue
    n += 1
    print(f"  {pid.decode('utf-8', 'replace')} 修復")
    if commit:
        # ★pid は bytes で読めているので **str に戻して**渡す
        #   (bytes のまま渡すと BLOB 比較になり 1行も当たらない)
        db.execute("UPDATE products SET images=? WHERE product_id=?",
                   (fixed.decode("utf-8"), pid.decode("utf-8")))
if commit:
    db.commit()
print(f"{n}行", "適用" if commit else "dry-run")
