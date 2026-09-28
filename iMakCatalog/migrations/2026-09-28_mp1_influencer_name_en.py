# -*- coding: utf-8 -*-
"""M-P-KC-019 の英語名を直す (2026-09-28).

判定: **①カタログのデータが誤り**。
`M-P-KC-019` (インフルエンサーの紹介 / コロちゃお付録・PSA ラベル MP1 #019) の `name_en` が
**`Quaxly`** になっていた。同じ番号の別カード `M-P-019` (クワッス) から写ったもの。

実害: PSA スラブ (cert164132291 `INFLUENCER'S INTRDCTN`) を引くと、名前照合が通らず
「カタログに無い」と出て出品できない。

正しい英語名 (2026-09-28 に Bulbapedia で確認):
    Influencer's Introduction
    (ページ `Influencer's Introduction (Start Deck 100 Battle Collection CoroCiao Version 19)`
     = 日本語版セット名・番号とも一致)

実行: python migrations/2026-09-28_mp1_influencer_name_en.py [--commit]
"""
import json
import sqlite3
import sys
from datetime import datetime

PID, NEW = "M-P-KC-019", "Influencer's Introduction"
db = sqlite3.connect("C:/dev/iMak_data/catalog/products.sqlite", timeout=300)
commit = "--commit" in sys.argv
row = db.execute("SELECT name_en, specs FROM products WHERE category='pokemon_tcg' "
                 "AND product_id=?", (PID,)).fetchone()
if not row:
    print(f"{PID} が無い"); sys.exit(0)
d = json.loads(row[1] or "{}")
print(f"{PID}: name_en {row[0]!r} -> {NEW!r} / character_name {d.get('character_name')!r} -> {NEW!r}")
if commit:
    d["character_name"] = NEW
    d["character_name_source"] = "name_en_20260928"
    db.execute("UPDATE products SET name_en=?, name_en_source=?, specs=?, updated_at=? "
               "WHERE category='pokemon_tcg' AND product_id=?",
               (NEW, "official_en_bulbapedia_jname_20260928",
                json.dumps(d, ensure_ascii=False),
                datetime.now().isoformat(timespec="seconds"), PID))
    db.commit()
    print("適用 1行")
