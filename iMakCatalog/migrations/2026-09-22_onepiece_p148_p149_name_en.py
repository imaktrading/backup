# -*- coding: utf-8 -*-
"""ワンピ P-148 / P-149 の英語名を埋める (2026-09-22).

判定: ①カタログのデータ不足。name_jp が全角数字 (`Mr.３(ギャルディーノ)`) のため、
同じキャラの既存行 (半角 `Mr.3(ギャルディーノ)` = `Mr.3(Galdino)` 21行 / `Mr.5(Gem)` 5行、
割れていない) に当たらず空欄になっていた。name_en の埋め方 1 (catalog 既存の英語名) で入れる。
"""
import json
import sqlite3
import sys
from datetime import datetime

c = sqlite3.connect("C:/dev/iMak_data/catalog/products.sqlite", timeout=120)
now = datetime.now().isoformat(timespec="seconds")
for pid, en in (("P-148", "Mr.3(Galdino)"), ("P-149", "Mr.5(Gem)")):
    if "--commit" in sys.argv:
        c.execute("update products set name_en=?, name_en_source='catalog_same_name_jp_20260922', updated_at=? "
                  "where category='one_piece_tcg' and product_id=? and coalesce(name_en,'')=''", (en, now, pid))
        sp = json.loads(c.execute("select specs from products where category='one_piece_tcg' and product_id=?",
                                  (pid,)).fetchone()[0])
        sp["character_name"] = en  # 同じキャラの既存23行と同じ値
        sp["character_name_source"] = "name_en_20260922"
        c.execute("update products set specs=? where category='one_piece_tcg' and product_id=?",
                  (json.dumps(sp, ensure_ascii=False), pid))
    print(pid, "->", en)
c.commit()
