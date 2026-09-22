# -*- coding: utf-8 -*-
"""英語版の画像を images から外し specs.images_en に移す (2026-09-22).

判定: ①カタログのデータ。ユーザー指示「英語版を保有するのはいいけど、使えないようにしたらいいだけ」。
images は目視と出品側が使う = 日本語の現物と照合する絵だけにする。英語版の絵は保有だけ (specs.images_en)。
英語版しか無い行は images が空になる = 「日本語の絵が無い」が正直に見える。
直前の `2026-09-22_tcg_images_ja_first.py` (並べ替え) の上に掛ける。
"""
import json
import sqlite3
import sys
from datetime import datetime

EN_MARKS = ("/OP-EN/", "/DBFW-EN/", "/GC-EN/", "_EN_")
c = sqlite3.connect("C:/dev/iMak_data/catalog/products.sqlite", timeout=120)
now = datetime.now().isoformat(timespec="seconds")
n = empty = 0
for rid, im, sp in c.execute("select id, images, specs from products where category in "
                             "('one_piece_tcg','dragonball_scg','gundam_tcg')").fetchall():
    L = json.loads(im or "[]")
    en = [u for u in L if any(k in u for k in EN_MARKS)]
    if not en:
        continue
    ja = [u for u in L if u not in en]
    d = json.loads(sp or "{}")
    d["images_en"] = list(dict.fromkeys((d.get("images_en") or []) + en))
    n += 1
    empty += not ja
    if "--commit" in sys.argv:
        c.execute("update products set images=?, specs=?, updated_at=? where id=?",
                  (json.dumps(ja, ensure_ascii=False), json.dumps(d, ensure_ascii=False), now, rid))
# 日本語の絵が無くなった行に「画像なし」の印を付ける (印の無い空欄は回帰テストが落とす)
m = 0
for rid, sp in c.execute("select id, specs from products where category in "
                         "('one_piece_tcg','dragonball_scg','gundam_tcg') and images='[]' "
                         "and json_extract(specs,'$.images_en') is not null "
                         "and json_extract(specs,'$.no_official_image') is null").fetchall():
    d = json.loads(sp)
    d["no_official_image"] = True
    d["no_official_image_reason"] = "日本語版の絵が無い。英語版の絵だけ持っている (specs.images_en。目視・出品には使わない)"
    d["no_official_image_checked_at"] = now
    d["no_official_image_probe"] = d["images_en"][0]
    m += 1
    if "--commit" in sys.argv:
        c.execute("update products set specs=? where id=?", (json.dumps(d, ensure_ascii=False), rid))
print(f"印を付けた {m}行")
c.commit()
print(f"{n}行 (うち日本語の絵が無くなる {empty}行)", "適用" if "--commit" in sys.argv else "dry-run")
