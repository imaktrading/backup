# -*- coding: utf-8 -*-
"""ワンピ / DB / ガンダムの images を「日本語を先頭」に並べ替える (2026-09-22).

判定: ①カタログのデータ (並び順) が誤り。
ユーザー指摘「P-106 英語版しかない」: 目視画面は images[0] だけ出すが、bandai-tcg-plus 由来の行は
EN 画像が先頭に入っていた。日本語版の画像は持っているのに見えていない (実測 9,840行)。

並び: 0 = 日本語 bandai-tcg-plus / 1 = 日本語 その他 (公式サイト等) / 2 = 英語。同じ組の中は元の順。
★公式サイト (onepiece-cardgame.com / gundam-gcg.com) は CORP same-site で画面に埋め込めないので
  bandai-tcg-plus の日本語を先にする。画像は消さない (並べ替えるだけ)。
"""
import json
import sqlite3
import sys
from datetime import datetime

EN_MARKS = ("/OP-EN/", "/DBFW-EN/", "/GC-EN/", "_EN_")


def rank(u: str) -> int:
    if any(k in u for k in EN_MARKS):
        return 2
    return 0 if "bandai-tcg-plus.com" in u else 1


c = sqlite3.connect("C:/dev/iMak_data/catalog/products.sqlite", timeout=120)
now = datetime.now().isoformat(timespec="seconds")
n = 0
for rid, im in c.execute("select id, images from products where category in "
                         "('one_piece_tcg','dragonball_scg','gundam_tcg')").fetchall():
    L = json.loads(im or "[]")
    S = sorted(L, key=rank)
    if S != L:
        n += 1
        if "--commit" in sys.argv:
            c.execute("update products set images=?, updated_at=? where id=?",
                      (json.dumps(S, ensure_ascii=False), now, rid))
c.commit()
print(n, "行", "適用" if "--commit" in sys.argv else "dry-run")
