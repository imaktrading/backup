#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""出品済みの UT 行に canonical KEY を書く (2026-09-12)。

なぜ (設計: iMakHQ/UT_FLOW.md):
    重複くんは KEY で二重出品を止める。UT は目視で商品を特定しているのに、KEY を
    書いていなかったので **重複くんからは無印の行**に見えていた。

守ること:
    - **出品してから書く**。B列 (itemID) が空の行には書かない
      (出品前の行に KEY があると「出品済み」と読まれ、その商品を二度と出せなくなる = orphan KEY 事故)
    - 色・サイズが決まっていない行には書かない (重複くんの申し送り。空 KEY を作らない)
    - 既に **カタログの** KEY がある行は触らない (人が入れた値を上書きしない)。
      ただし `item:` / `shops:` で始まる値は仕入元URL由来で、カタログの KEY ではないので
      入れ替える (2026-09-12: ここを「値が入っている」で飛ばしていたため、目視しても
      出品済み57行に KEY が入らなかった)
    - KEY = `uniqlo_ut:<商品番号>:<色>:<サイズ>` (UT は 1出品 = 1色1サイズ)

使い方:
    python ut_key_backfill.py            # 何件書くか出すだけ
    python ut_key_backfill.py --write    # 実際に書く
"""
from __future__ import annotations

import argparse
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, r"C:\dev\iMak\iMakMercari")

CATEGORY = "Tシャツ"
COL_URL, COL_ITEMID, COL_CAT, COL_SIZE, COL_KEY = 0, 1, 17, 19, 34


def plan(rows2d, ledger):
    """書く行を決める (純関数) → [{"row","item_id","key","title"}]。

    対象: R列=Tシャツ ∩ B列に itemID ∩ AI列が空 ∩ 台帳で特定済み(go) ∩ 色・サイズが決まる。
    """
    import ut_catalog_values as V
    out = []
    for i, r in enumerate(rows2d[1:], start=2):
        if len(r) <= COL_CAT or (r[COL_CAT] or "").strip() != CATEGORY:
            continue
        iid = (r[COL_ITEMID] or "").strip()
        if not iid:
            continue                                   # 出品してから書く
        if not V.needs_catalog_key(r[COL_KEY] if len(r) > COL_KEY else ""):
            continue                                   # 既にカタログの KEY / 人が入れた値 = 触らない
        e = (ledger or {}).get((r[COL_URL] or "").strip())
        if not e or e.get("decision") != "go":
            continue
        size = V.jp_size((r[COL_SIZE] if len(r) > COL_SIZE else "") or e.get("size") or
                         (r[2] if len(r) > 2 else ""))
        key = V.identity_key_of(e, size)
        if not key:
            continue                                   # 色・サイズが決まらない = 書かない
        out.append({"row": i, "item_id": iid, "key": key,
                    "title": (r[2] if len(r) > 2 else "")[:40]})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    import sheet_io
    import ut_catalog_values as V
    rows = sheet_io._product_ws().get_all_values()
    todo = plan(rows, V.load_ledger())
    print(f"KEY を書く対象: {len(todo)}件")
    for t in todo[:20]:
        print(f"  行{t['row']} {t['item_id']} {t['key']}  {t['title']}")
    if not todo:
        return 0
    if not a.write:
        print("→ 実際に書くには --write")
        return 0
    n = sheet_io.write_keys({t["item_id"]: t["row"] for t in todo},
                            {t["item_id"]: t["key"] for t in todo})
    print(f"✅ {n}行に KEY を書きました")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
