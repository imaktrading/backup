# -*- coding: utf-8 -*-
"""自分の番号の公式画像を images の先頭に置く (2026-09-28).

依頼: `requests/2026-09-27_pokemon_ma_rarity_and_op_parallel_rows.md` の B。
判定: **①カタログの並びが誤り**。

実害: 通常版の行 `OP09-051` の先頭が bandai の `OP09_051_SP_dummy.png` (= WANTED の別絵柄) で、
目視画面でも出品でも「別絵柄」が通常版として出ていた。公式画像を並べて確認済
(公式 `/cardlist/card/OP09-051.png` は通常絵、`_p3` が WANTED)。

直し方: **その行の番号と完全に一致する公式画像**があれば先頭に置く。
`_d.png` / `_sample.png` のような bandai 側の名前で中身を決めつけない
(番号一致の公式画像はその行の絵そのものなので、名前を見ずに正と言える)。
画像は消さない (並べ替えるだけ)。

実行: python migrations/2026-09-28_op_images_own_official_first.py [--commit]
"""
import json
import re
import sqlite3
import sys
from datetime import datetime

DB = "C:/dev/iMak_data/catalog/products.sqlite"
# ★ワンピだけ。ドラゴンボールは「表面 (_f) を先頭に置く」別の決まりがあり
#   (CLAUDE.md 両面カード規約)、番号一致の `<pid>.webp` を先頭にすると
#   listing 側の `_f -> _b` 裏面導出が壊れる。ガンダム/ポケモンは実害の報告が無いので触らない。
CATS = ("one_piece_tcg",)
commit = "--commit" in sys.argv
db = sqlite3.connect(DB, timeout=300)
now = datetime.now().isoformat(timespec="seconds")
n = 0
for cat, pid, im in db.execute(
        f"SELECT category, product_id, images FROM products "
        f"WHERE category IN ({','.join('?' * len(CATS))})", CATS).fetchall():
    L = json.loads(im or "[]")
    if not L:
        continue
    tail = {f"/{pid}.png", f"/{pid}.jpg", f"/{pid}.webp"}
    own = [u for u in L if any(u.replace("\\", "/").endswith(t) for t in tail)]
    if not own or L[0] in own:
        continue
    new = own + [u for u in L if u not in own]
    n += 1
    if n <= 8:
        print(f"  {cat:14} {pid:22} {L[0].split('/')[-1]} -> {new[0].split('/')[-1]}")
    if commit:
        db.execute("UPDATE products SET images=?, updated_at=? WHERE category=? AND product_id=?",
                   (json.dumps(new, ensure_ascii=False), now, cat, pid))
if commit:
    db.commit()
print(f"{n}行", "適用" if commit else "dry-run")
