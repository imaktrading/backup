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


def plan(rows2d, mp, key_col=S.PRODUCT_COL_KEY, other_cat_pids=frozenset(), category="one_piece_tcg"):
    """シート → 書き換え [(行番号, 今の KEY, 新しい KEY, itemID)] (純関数)。表に無い KEY は触らない。

    mp: {古い pid: 本体の pid} (1カテゴリ分) または {カテゴリ: {古い: 本体}} (複数カテゴリを1回で)。
    ★2026-10-06 (ADV 指摘): 接頭辞の無い KEY (`OP08-106_p` だけ) が 22行あり素通りしていた。
      `:` の後ろ (無ければ全体) で突き合わせ、接頭辞の有無は今の行のまま保つ。
      接頭辞が無い行は、番号が **ちょうど1カテゴリの表** にだけ在り、かつ他のゲームのカタログにも
      無い (other_cat_pids) 時だけ書く。どのゲームか決まらない物は触らない。
    大文字小文字は区別する (`_P` プロモ と `_p` パラレルは別カード)。
    """
    maps = mp if mp and all(isinstance(v, dict) for v in mp.values()) else {category: mp or {}}
    others = other_cat_pids if isinstance(other_cat_pids, dict) else {c: other_cat_pids for c in maps}
    out = []
    for n, r in enumerate(rows2d[1:], 2):
        k = (r[key_col] if len(r) > key_col else "").strip()
        if not k:
            continue
        if ":" in k:
            cat, pid = k.split(":", 1)
            new = (maps.get(cat) or {}).get(pid)
            pre = cat + ":"
        else:
            hits = [(c, m[k]) for c, m in maps.items() if k in m and k not in (others.get(c) or ())]
            if len(hits) != 1 or sum(1 for m in maps.values() if k in m) != 1:
                continue
            new, pre = hits[0][1], ""
        if new:
            out.append((n, k, pre + new, (r[1] if len(r) > 1 else "").strip()))
    return out


def other_category_pids(pids, category="one_piece_tcg", db=r"C:/dev/iMak_data/catalog/products.sqlite"):
    """pids のうち category 以外のカテゴリにも在る物 (I/O・読むだけ)。"""
    import sqlite3
    pids = list(pids)
    if not pids:
        return frozenset()
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        q = ",".join("?" * len(pids))
        return frozenset(r[0] for r in con.execute(
            f"SELECT DISTINCT product_id FROM products WHERE category != ? AND product_id IN ({q})",
            [category] + pids))
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
    # 引数: <カテゴリ>=<対応表.csv> を並べる (1回で書き換え・控えは1本)。カテゴリ無しの表は one_piece_tcg
    maps = {}
    for a in argv:
        if a.startswith("--"):
            continue
        cat, path = a.split("=", 1) if "=" in a and not a[1:3] == ":/" and a.split("=", 1)[0].isidentifier() \
            else ("one_piece_tcg", a)
        maps.setdefault(cat, {}).update(load_map(path))
    write = "--write" in argv
    ws = S._product_ws()
    rows = ws.get_all_values()
    others = {c: other_category_pids(m, c) for c, m in maps.items()}
    for c, o in others.items():
        if o:
            print(f"  ({c}: 接頭辞なしの行では触らない = 他のゲームにも同じ番号 {len(o)}件 {sorted(o)[:5]})")
    pl = plan(rows, maps, other_cat_pids=others)
    live = sum(1 for _n, _o, _k, i in pl if i and i != "9999")
    print(f"対応表 {', '.join(f'{c} {len(m)}行' for c, m in maps.items())} → 書き換え {len(pl)}行 (出品中 {live})")
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
