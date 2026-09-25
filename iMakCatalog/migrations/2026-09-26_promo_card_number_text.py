# -*- coding: utf-8 -*-
"""promo 取り込み 50件に card_number_text を入れる (2026-09-26).

依頼: `requests/2026-09-25_promo_ingest_card_number_text_missing.md`
判定: ①カタログのデータが誤り。**正のキーは `card_number_text`** (出品くん・テストが読む方)。
9/5 の promo 取り込み (`2026-09-05_op_promo_rows.py`) が `card_number` の名前で書いていた。
取り込み側も同時に直したので、次回からは最初から正しい名前で入る。

値は specs.card_number をそのまま移す (公式ページの券面番号。新たに調べる必要はない)。
移した後は `card_number` を消す — 同じ値が2つの名前で残ると、また別の所が古い方を読む。

実行: python migrations/2026-09-26_promo_card_number_text.py [--commit]
"""
import json
import sqlite3
import sys
from datetime import datetime

db = sqlite3.connect("C:/dev/iMak_data/catalog/products.sqlite", timeout=300)
commit = "--commit" in sys.argv
now = datetime.now().isoformat(timespec="seconds")
n = 0
for pid, sp in db.execute(
        "SELECT product_id, specs FROM products WHERE category='one_piece_tcg' "
        "AND json_extract(specs,'$.card_number') IS NOT NULL "
        "AND json_extract(specs,'$.card_number_text') IS NULL").fetchall():
    d = json.loads(sp)
    d["card_number_text"] = d.pop("card_number")
    n += 1
    print(f"  {pid:18} card_number_text = {d['card_number_text']}")
    if commit:
        db.execute("UPDATE products SET specs=?, updated_at=? WHERE product_id=?",
                   (json.dumps(d, ensure_ascii=False), now, pid))
if commit:
    db.commit()
print(f"{n}行", "適用" if commit else "dry-run")
