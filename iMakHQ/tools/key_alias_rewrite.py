#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""商品管理シートの KEY (AI列) を、カタログの対応表どおり「本体の KEY」に書き換える (2026-10-06)。

ADV 依頼 (カタログが bandai 由来と公式由来の二重登録を alias で寄せた・057314d)。読み替えではなく
シートの KEY を書き換える (読む側が複数あり、どこかで入れ忘れると片方だけズレるため)。

守ること (ADV と合意): 控えを取る / 対応表に無い行は触らない / 書く直前に読み直し、違えば書かない。

    python key_alias_rewrite.py <対応表.csv>            # 計画だけ
    python key_alias_rewrite.py <対応表.csv> --write    # 書く (控え iMak_data/hq/key_alias_rewrite_backup_*.json)
"""
from __future__ import annotations

import csv
import datetime as _dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sheet_io as S  # noqa: E402

PREFIX = "one_piece_tcg:"
BACKUP_DIR = r"C:\dev\iMak_data\hq"


def load_map(path):
    """対応表 → {古い pid: 本体の pid} (純関数に近い I/O)。"""
    out = {}
    with open(path, encoding="utf-8-sig", newline="") as f:
        for r in csv.reader(f):
            if len(r) < 2 or r[0].startswith("古い"):
                continue
            old, new = r[0].strip(), r[1].strip()
            if old and new and old != new:
                out[old] = new
    return out


def plan(rows2d, mp, key_col=S.PRODUCT_COL_KEY, other_cat_pids=frozenset()):
    """シート → 書き換え [(行番号, 今の KEY, 新しい KEY, itemID)] (純関数)。表に無い KEY は触らない。

    ★2026-10-06 (ADV 指摘): 接頭辞 `one_piece_tcg:` の無い KEY (`OP08-106_p` だけ) が 22行あり素通りしていた。
      `:` の後ろ (無ければ全体) で突き合わせ、接頭辞の有無は今の行のまま保つ。
      接頭辞が無く、同じ番号が他のゲームにもある (other_cat_pids) 行は、どのゲームか決まらないので触らない。
    """
    out = []
    for n, r in enumerate(rows2d[1:], 2):
        k = (r[key_col] if len(r) > key_col else "").strip()
        if not k:
            continue
        if ":" in k:
            if not k.startswith(PREFIX):
                continue                                # 別のゲームの KEY
            pid, pre = k[len(PREFIX):], PREFIX
        else:
            pid, pre = k, ""
            if pid in other_cat_pids:
                continue
        new = mp.get(pid)
        if new:
            out.append((n, k, pre + new, (r[1] if len(r) > 1 else "").strip()))
    return out


def other_category_pids(pids, db=r"C:/dev/iMak_data/catalog/products.sqlite"):
    """pids のうち one_piece_tcg 以外のカテゴリにも在る物 (I/O・読むだけ)。"""
    import sqlite3
    pids = list(pids)
    if not pids:
        return frozenset()
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        q = ",".join("?" * len(pids))
        return frozenset(r[0] for r in con.execute(
            f"SELECT DISTINCT product_id FROM products WHERE category != 'one_piece_tcg' AND product_id IN ({q})", pids))
    finally:
        con.close()


def _col(c):
    s, c = "", c + 1
    while c:
        c, r = divmod(c - 1, 26)
        s = chr(65 + r) + s
    return s


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:                                          # noqa: BLE001
        pass
    mp = load_map(argv[0])
    write = "--write" in argv
    ws = S._product_ws()
    rows = ws.get_all_values()
    others = other_category_pids(mp)
    if others:
        print(f"  (接頭辞なしの行では触らない: 他のゲームにも同じ番号 {len(others)}件 {sorted(others)[:5]})")
    pl = plan(rows, mp, other_cat_pids=others)
    live = sum(1 for _n, _o, _k, i in pl if i and i != "9999")
    print(f"対応表 {len(mp)}行 → 書き換え {len(pl)}行 (出品中 {live})")
    for n, old, new, iid in pl[:200]:
        print(f"  {n}行 itemID={iid or '(出品待ち)'} {old} → {new}")
    if not write or not pl:
        print("(書いていない。--write で書く)" if pl else "✅ 書き換え0件")
        return 0
    col = _col(S.PRODUCT_COL_KEY)
    fresh = ws.get_all_values()
    ups, backup = [], []
    for n, old, new, iid in pl:
        now = (fresh[n - 1][S.PRODUCT_COL_KEY] if len(fresh[n - 1]) > S.PRODUCT_COL_KEY else "").strip()
        if now != old:
            print(f"  ⏭ {n}行 は読んだ後に変わった ({now}) → 書かない")
            continue
        ups.append({"range": f"{col}{n}", "values": [[new]]})
        backup.append({"row": n, "itemID": iid, "old": old, "new": new})
    path = os.path.join(BACKUP_DIR, f"key_alias_rewrite_backup_{_dt.datetime.now():%Y%m%d_%H%M%S}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(backup, f, ensure_ascii=False, indent=1)
    if ups:
        ws.batch_update(ups, value_input_option="RAW")
    print(f"✅ {len(ups)}行 書き換えた (控え {path})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
