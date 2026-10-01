# -*- coding: utf-8 -*-
"""Features は eBay の一覧に在る綴りで持つ — `Alt Art` を 0 で維持する.

2026-10-01 実測: 同じ「別絵柄」を `Alt Art` 3,005行 / `Alternative Art` 1,371行 の
2つの綴りで持っていた。eBay の一覧 (`aspects.Features.all`) に在るのは
`Alternative Art` だけ。`migrations/2026-10-01_features_alt_art_to_ebay_value.py` で揃えた。

今の書き手 (`migrations/2026-08-22_features_fill.py`) は `Alternative Art` を書くので、
増えるとしたら新しい取り込みが古い綴りを足した時。ここで止める。
"""
import json
import sqlite3

DB = "C:/dev/iMak_data/catalog/products.sqlite"
BAD = "Alt Art"


def test_no_alt_art_spelling_left():
    c = sqlite3.connect(DB, timeout=120)
    try:
        bad = []
        for cat, pid, sp in c.execute(
                "SELECT category, product_id, specs FROM products WHERE specs LIKE '%Alt Art%'"):
            try:
                f = json.loads(sp or "{}").get("features")
            except ValueError:
                continue
            if isinstance(f, list) and BAD in f:
                bad.append(f"{cat}/{pid}")
    finally:
        c.close()
    assert not bad, f"{BAD} の綴りが {len(bad)}行 残っている: {bad[:5]}"
