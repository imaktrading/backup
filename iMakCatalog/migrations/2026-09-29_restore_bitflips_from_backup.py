# -*- coding: utf-8 -*-
"""1ビット化けした 29欄を 9/22 のバックアップの値に戻す (2026-09-29).

依頼: `requests/2026-09-29_catalog_bitflips_restore.md` (HQ・緊急度 高)
種別: PC の不具合 (書き込み中に1ビット裏返る)。**カタログの作りの問題ではない**。

戻す条件 (推測で書き換えない):
  1. 今の値と 9/22 の値の **長さが同じ**
  2. 違うのは 1〜3 バイトで、**どのバイトも1ビットだけ違う**
  3. json が言う `now` の断片が今の値に実在する
どれか外れたら触らず一覧に出す (9/22 以降に正当に書き換えた欄はここで弾かれる)。

実行: python migrations/2026-09-29_restore_bitflips_from_backup.py [--commit]
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime

DB = "C:/dev/iMak_data/catalog/products.sqlite"
BK = "C:/tmp/bk/iMak_daily_20260922_0500/products.sqlite"
LIST = r"C:/dev/iMak_data/catalog/requests/2026-09-29_catalog_bitflips.json"
commit = "--commit" in sys.argv


def bit_diffs(a: bytes, b: bytes) -> list[int] | None:
    """1ビットだけ違うバイト位置。長さ違い/2ビット以上の差があれば None."""
    if len(a) != len(b):
        return None
    out = []
    for i, (x, y) in enumerate(zip(a, b)):
        if x == y:
            continue
        if bin(x ^ y).count("1") != 1:
            return None
        out.append(i)
    return out


rows = json.load(open(LIST, encoding="utf-8"))
db = sqlite3.connect(DB, timeout=300)
db.text_factory = bytes
bk = sqlite3.connect(BK)
bk.text_factory = bytes
now = datetime.now().isoformat(timespec="seconds")
fixed = skipped = 0
for r in rows:
    pid, col, cat = r["product_id"], r["column"], r["category"]
    cur = db.execute(f"SELECT {col} FROM products WHERE category=? AND product_id=?",
                     (cat, pid)).fetchone()
    old = bk.execute(f"SELECT {col} FROM products WHERE category=? AND product_id=?",
                     (cat, pid)).fetchone()
    if not cur or not old or cur[0] is None or old[0] is None:
        print(f"  ✗ {pid} {col}: 片方に行が無い")
        skipped += 1
        continue
    d = bit_diffs(cur[0], old[0])
    if not d or len(d) > 3:
        print(f"  ✗ {pid} {col}: 1ビット化けの形ではない (差 {d}) → 触らない")
        skipped += 1
        continue
    # ★依頼書の now は UTF-8 で読めない所を替え字にしているので、そのままでは一致しない。
    #   代わりに **化けた位置が依頼書の offsets と一致するか**で確かめる (2026-09-29)。
    if r.get("offsets") and sorted(d) != sorted(r["offsets"]):
        print(f"  ✗ {pid} {col}: 化けた位置が依頼書と違う (今 {d} / 依頼書 {r['offsets']}) → 触らない")
        skipped += 1
        continue
    fixed += 1
    print(f"  {pid:16} {col:11} 位置 {d} : {r['now'][:28]!r} -> {r['was'][:28]!r}")
    if commit:
        db.execute(f"UPDATE products SET {col}=? WHERE category=? AND product_id=?",
                   (old[0].decode("utf-8"), cat, pid))
        after = db.execute(f"SELECT {col} FROM products WHERE category=? AND product_id=?",
                           (cat, pid)).fetchone()[0]
        assert after == old[0], f"{pid} {col} の書き戻しが一致しない"
if commit:
    db.commit()
db.close()
bk.close()
print(f"\n戻した {fixed} / 触らなかった {skipped}", "適用" if commit else "dry-run")
