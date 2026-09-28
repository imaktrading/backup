# -*- coding: utf-8 -*-
"""MA の eBay 値を Master Ball -> Mega Attack Rare に直す (2026-09-28).

依頼: `requests/2026-09-27_pokemon_ma_rarity_and_op_parallel_rows.md`
判定: **①カタログの変換表が誤り**。出品くんは写しただけ。

根拠 (2026-09-28 にその場で取り直した):
  - 公式画像 M2a/049984 の券面右下 = `224/193 MA`
  - PSA ラベル (cert145973199) = `MEGA FROSLASS ex / MEGA ATTACK RARE`
  → MA は **メガアタックレア**。マスターボール柄 (MB) とは別物

eBay の Rarity は FREE_TEXT で、一覧57値に該当語が無い。
既存も `Art Rare` / `Hyper Rare` 等、一覧に無い値を自由入力で入れているので同じ形にする
(空欄にしない = セット名の②と同じ考え方)。

実行: python migrations/2026-09-28_pokemon_ma_mega_attack_rare.py [--commit]
"""
import json
import sqlite3
import sys
from datetime import datetime

DB = "C:/dev/iMak_data/catalog/products.sqlite"
OLD, NEW = "Master Ball", "Mega Attack Rare"
commit = "--commit" in sys.argv
db = sqlite3.connect(DB, timeout=300)
now = datetime.now().isoformat(timespec="seconds")

cur = db.execute("SELECT ebay_value FROM ebay_filter_map WHERE category='pokemon_tcg' "
                 "AND field='rarity' AND source_value='MA'").fetchone()
print(f"変換表 MA: {cur[0] if cur else '(無し)'} -> {NEW}")
if commit:
    db.execute("UPDATE ebay_filter_map SET ebay_value=?, note=? WHERE category='pokemon_tcg' "
               "AND field='rarity' AND source_value='MA'",
               (NEW, "2026-09-28 是正: MA はメガアタックレア (公式券面 224/193 MA + PSA ラベル "
                     "MEGA ATTACK RARE)。旧 'Master Ball' は誤り"))

n = 0
for pid, sp in db.execute(
        "SELECT product_id, specs FROM products WHERE category='pokemon_tcg' "
        "AND json_extract(specs,'$.rarity')='MA'").fetchall():
    d = json.loads(sp)
    if d.get("rarity_ebay") == NEW:
        continue
    d["rarity_ebay"] = NEW
    d["rarity_ebay_source"] = "filter_map_ma_fix_20260928"
    n += 1
    print(f"  {pid} {d.get('name_jp','')} -> {NEW}")
    if commit:
        db.execute("UPDATE products SET specs=?, updated_at=? WHERE category='pokemon_tcg' "
                   "AND product_id=?", (json.dumps(d, ensure_ascii=False), now, pid))
if commit:
    db.commit()
print(f"{n}行", "適用" if commit else "dry-run")
