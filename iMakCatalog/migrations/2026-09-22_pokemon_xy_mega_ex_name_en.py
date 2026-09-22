# -*- coding: utf-8 -*-
"""XY 期のメガ (MギャラドスEX 等) の英語名 (2026-09-22).

判定: ①カタログのデータ欠落。依頼 requests/2026-09-22_pokemon_xy_mega_ex_missing.md
scraper が公式の `<span class="pcg pcg-megamark">` を剥がして落としていたため 88行が未登録だった
(同日 scraper を直して取り込み済み)。

英語名は **メガでない同じポケモンの EX** の catalog 既存値 (37種とも1値に決まる) に `M ` を付ける。
英語版カードの表記は `M Gyarados-EX` の形なので、`Glalie EX` のような表記揺れは `-EX` に揃える。
character_name も同じ値 (既存のメガ行と同じ持ち方)。
"""
import json
import sqlite3
import sys
from datetime import datetime

c = sqlite3.connect("C:/dev/iMak_data/catalog/products.sqlite", timeout=120)
now = datetime.now().isoformat(timespec="seconds")
n = 0
for pid, jp, sp in c.execute(
        "select product_id, name_jp, specs from products where category='pokemon_tcg' "
        "and name_jp like 'M%EX' and name_jp not like 'Mr%' and coalesce(name_en,'')=''").fetchall():
    ens = {e for (e,) in c.execute(
        "select name_en from products where category='pokemon_tcg' and name_jp=? and coalesce(name_en,'')!=''",
        (jp[1:],))}
    ens = {e[:-2].rstrip(" -") + "-EX" for e in ens if e.endswith("EX")}
    if len(ens) != 1:
        print("決まらない", pid, jp, ens)
        continue
    en = "M " + ens.pop()
    d = json.loads(sp or "{}")
    d["character_name"] = en
    d["character_name_source"] = "name_en_20260922"
    n += 1
    print(pid, jp, "->", en)
    if "--commit" in sys.argv:
        c.execute("update products set name_en=?, name_en_source='xy_mega_rule_from_base_ex_20260922', specs=?, updated_at=? "
                  "where category='pokemon_tcg' and product_id=?", (en, json.dumps(d, ensure_ascii=False), now, pid))
c.commit()
print(n, "行", "適用" if "--commit" in sys.argv else "dry-run")
