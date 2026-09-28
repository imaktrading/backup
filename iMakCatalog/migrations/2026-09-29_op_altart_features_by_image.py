# -*- coding: utf-8 -*-
"""別絵柄なのに Features が空だったワンピの行に Alternative Art を付ける (2026-09-29).

依頼: `requests/2026-09-28_eb04_061_p1_features_missing.md`
判定: **①カタログのデータが誤り**。

## 何が起きていたか
`variant_type` は 2026-05-29 の付け直しで **画像URLのフォルダ名を先に見る**作りだった:

    /PRB\d+/ -> premium_booster   /ST\d+/ -> starter_deck
    /EB\d+/  -> event             /P/     -> promo        (URL が優先)
    _p\d+    -> parallel                                   (suffix は後)

そのため **EB (エクストラブースター) 収録の `_pN` が全部 `event`** になり、
Features を付ける migration (2026-08-22) の `alt_art -> Alternative Art` に当たらなかった。
★`/EB\d+/ -> event` という対応自体も誤り (EB = エクストラブースターであってイベントではない)。
ここでは Features だけを直し、variant_type の付け直しは触らない (別絵柄という事実は下の照合で足りる)。

## 直す根拠 (名前や suffix で決めない)
手元に保管した**公式画像**で、`<番号>_pN` と `<番号>` の中身を md5 で突き合わせ、
**絵が違う行だけ**に `Alternative Art` を足す。実測 (2026-09-29):

    既に Alternative Art  1,415行
    絵が違う (= 別絵柄)     183行  ← これを直す
    絵が同じ                  0行
    絵を持っていない        101行  ← 触らない

実行: python migrations/2026-09-29_op_altart_features_by_image.py [--commit]
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
import sqlite3
import sys
from datetime import datetime

DB = "C:/dev/iMak_data/catalog/products.sqlite"
MIR = pathlib.Path("C:/dev/iMak_data/catalog/_official_images/one_piece_tcg")
PAT = re.compile(r"^(.+-\d+)_p\d+$")
commit = "--commit" in sys.argv


def md5(pid: str) -> str | None:
    p = MIR / f"{pid}.png"
    return hashlib.md5(p.read_bytes()).hexdigest() if p.exists() else None


db = sqlite3.connect(DB, timeout=300)
now = datetime.now().isoformat(timespec="seconds")
n = 0
for pid, sp in db.execute("SELECT product_id, specs FROM products "
                          "WHERE category='one_piece_tcg'").fetchall():
    m = PAT.match(pid)
    if not m:
        continue
    d = json.loads(sp or "{}")
    cur = d.get("features_ebay")
    if cur and "Alternative" in str(cur):
        continue
    a, b = md5(pid), md5(m.group(1))
    if a is None or b is None or a == b:
        continue                      # 絵を持っていない / 同じ絵は触らない
    vals = cur if isinstance(cur, list) else ([cur] if cur else [])
    d["features_ebay"] = vals + ["Alternative Art"]
    d["features_ebay_source"] = "official_image_differs_20260929"
    n += 1
    if n <= 6:
        print(f"  {pid:18} {d.get('variant_type')!r} {cur!r} -> {d['features_ebay']}")
    if commit:
        db.execute("UPDATE products SET specs=?, updated_at=? WHERE category='one_piece_tcg' "
                   "AND product_id=?", (json.dumps(d, ensure_ascii=False), now, pid))
if commit:
    db.commit()
print(f"{n}行", "適用" if commit else "dry-run")
