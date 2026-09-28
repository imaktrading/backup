# -*- coding: utf-8 -*-
"""別のカードから写った英語名を直す (2026-09-28).

判定: **①カタログのデータが誤り**。
`M-P-KC-019` が `Quaxly` になっていた件 (同じ番号の `M-P-019` クワッス から写った) を直した時に、
同じ形の取り違えを横断で洗って見つかった分。

見つけ方: 同じ英語名を複数の日本語名が使っていて、**少数派 (1〜2行) の方**が別カードのもの。
値は 2026-09-28 に Bulbapedia のカードページで
`(Japanese: '''<日本語名>''')` が一致するものだけ採った (推測しない)。

    ウルトラボール      Ultra Ball   -> Beast Ball
    ギリギリポーション  Potion       -> Last Chance Potion
    いいつりざお        Super Rod    -> Good Rod
    活力剤              Vitality Band-> Revitalizer
    帯電鉱脈            Electric Generator -> Conductive Quarry
    キャンセルコロン    Reset Stamp  -> Canceling Cologne
    ギーマの一手        Colress's Experiment -> Grimsley's Move
    きんきゅうゼリー    Emergency Jelly (既に正しい語だが 緊急ボード と混在) -> Emergency Jelly

★`ポワルン 太陽の姿` / `シャワーズ☆` は Bulbapedia で確かめられなかったので**触らない**。

実行: python migrations/2026-09-28_pokemon_name_en_miscopied.py [--commit]
"""
import json
import sqlite3
import sys
from datetime import datetime

FIX = {
    "ウルトラボール": "Beast Ball",
    "ギリギリポーション": "Last Chance Potion",
    "いいつりざお": "Good Rod",
    "活力剤": "Revitalizer",
    "帯電鉱脈": "Conductive Quarry",
    "キャンセルコロン": "Canceling Cologne",
    "ギーマの一手": "Grimsley's Move",
    "きんきゅうゼリー": "Emergency Jelly",
}
db = sqlite3.connect("C:/dev/iMak_data/catalog/products.sqlite", timeout=300)
commit = "--commit" in sys.argv
now = datetime.now().isoformat(timespec="seconds")
n = 0
for jp, en in FIX.items():
    for pid, cur, sp in db.execute(
            "SELECT product_id, name_en, specs FROM products WHERE category='pokemon_tcg' "
            "AND name_jp=?", (jp,)).fetchall():
        if cur == en:
            continue
        d = json.loads(sp or "{}")
        print(f"  {pid:14} {jp:12} {cur!r} -> {en!r}")
        n += 1
        if commit:
            if d.get("character_name") == cur:
                d["character_name"] = en
                d["character_name_source"] = "name_en_20260928"
            db.execute("UPDATE products SET name_en=?, name_en_source=?, specs=?, updated_at=? "
                       "WHERE category='pokemon_tcg' AND product_id=?",
                       (en, "official_en_bulbapedia_jname_20260928",
                        json.dumps(d, ensure_ascii=False), now, pid))
if commit:
    db.commit()
print(f"{n}行", "適用" if commit else "dry-run")
