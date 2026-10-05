#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""同じ1点ものの仕入元を2行以上が持っている組を、1行にだけ残す (2026-10-06 ADV 依頼・ユーザー指示)。

ユーザー「目視に間違う可能性を出す作りが悪いなら直せよ」。1枚しか無い個体を2つの出品が補に持つと、
片方が売れた時にもう片方は履行できない。発生源は直した (sheet_io.drop_claimed_supply が補の列も見る /
psa_hoju_fill の目視が出品待ちの行も持ち主に数える)。これは **もう入っている分** を洗う道具。

残し方 (決めた順に当てる・判断を足さない):
  1. 出品待ちの行の A列 (重複くんが止めている2枚目の記録) は触らない
  2. 同じ行の中で重なっている物は1本にする (A列にあれば補の方を消す)
  3. 出品中 (itemID あり・9999 以外) の行があれば、出品中の行に残し、他の行の補から消す
  4. 出品中が2行以上なら、URL ごとに交互に振り分ける (両方に予備が残るように)
  5. 出品中が無ければ、上の行に残す

消すのは補URL (AC〜AG) だけ。書く直前に今の値を読み直し、計画と違えば書かない。

    python shared_supply_cleanup.py            # 計画を出すだけ
    python shared_supply_cleanup.py --write    # 書く (控えを iMak_data/hq に残す)
"""
from __future__ import annotations

import collections
import datetime as _dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sheet_io as S  # noqa: E402

AUX0, AUXN = S.PRODUCT_COL_AUX_START, S.PRODUCT_AUX_MAX
BACKUP_DIR = r"C:\dev\iMak_data\hq"


def _cell(r, i):
    return r[i].strip() if len(r) > i else ""


def holdings(rows2d, norm):
    """全行 → {正規化URL: [(行番号, 列, itemID)]} (純関数)。売り切れ (D) の行は数えない。"""
    own = collections.defaultdict(list)
    for n, r in enumerate(rows2d[1:], 2):
        if _cell(r, 3):
            continue
        for col in [0] + list(range(AUX0, AUX0 + AUXN)):
            u = _cell(r, col)
            if u and S.is_one_of_a_kind(u):
                own[norm(u)].append((n, col, _cell(r, 1)))
    return own


def _live(iid):
    return bool(iid) and iid != "9999"


def plan(own):
    """{URL: 持ち主} → 消すセル [(行番号, 列, URL)] (純関数)。上の残し方 1〜5 をそのまま当てる。"""
    removes = []
    turn = collections.Counter()                # 出品中どうしの交互振り分け (行の組ごと)
    for u in sorted(own):
        hs = own[u]
        if len({n for n, _c, _i in hs}) < 2 and len(hs) < 2:
            continue
        # 2. 同じ行の中の重なり: A列にあれば補を消す / 補どうしなら最初の1本だけ残す
        by_row = collections.defaultdict(list)
        for n, c, i in hs:
            by_row[n].append((c, i))
        kept = []
        for n, cs in by_row.items():
            cs = sorted(cs)
            for c, _i in cs[1:]:
                removes.append((n, c, u))
            kept.append((n, cs[0][0], cs[0][1]))
        if len(kept) < 2:
            continue
        a_rows = [(n, c, i) for n, c, i in kept if c == 0]
        aux_rows = [(n, c, i) for n, c, i in kept if c != 0]
        live = [(n, c, i) for n, c, i in aux_rows if _live(i)]
        if a_rows:
            # 1. A列の持ち主は触らない。補の持ち主のうち 出品中は残し (重複くんの2枚目の記録と共存する作り)、
            #    出品待ち・9999 の補は消す
            for n, c, i in aux_rows:
                if not _live(i):
                    removes.append((n, c, u))
            if len([x for x in a_rows if _live(x[2])]) + len(live) < 2:
                continue
            # A列が出品中で、補にも出品中がある = 出品中どうしの共有 → 補の側から消す
            if any(_live(x[2]) for x in a_rows):
                for n, c, i in live:
                    removes.append((n, c, u))
            elif len(live) >= 2:
                keep = sorted(live)[turn[tuple(sorted(x[0] for x in live))] % len(live)]
                turn[tuple(sorted(x[0] for x in live))] += 1
                removes.extend((n, c, u) for n, c, i in live if (n, c, i) != keep)
            continue
        if live:
            # 3. 出品中に残す (出品待ち・9999 の補は消す)。4. 出品中が2つ以上なら交互
            for n, c, i in aux_rows:
                if not _live(i):
                    removes.append((n, c, u))
            if len(live) >= 2:
                same_listing = len({i for _n, _c, i in live}) == 1
                key = tuple(sorted(x[0] for x in live))
                keep = sorted(live)[0] if same_listing else sorted(live)[turn[key] % len(live)]
                turn[key] += 1
                removes.extend((n, c, u) for n, c, i in live if (n, c, i) != keep)
        else:
            # 5. 出品中が無い → 上の行に残す
            keep = sorted(aux_rows)[0]
            removes.extend((n, c, u) for n, c, i in aux_rows if (n, c, i) != keep)
    return sorted(set(removes))


def _col_letter(c):
    s = ""
    c += 1
    while c:
        c, r = divmod(c - 1, 26)
        s = chr(65 + r) + s
    return s


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    write = "--write" in argv
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:                                          # noqa: BLE001
        pass
    import dup_guard
    ws = S._product_ws()
    rows = ws.get_all_values()
    own = holdings(rows, lambda u: dup_guard.norm_url(u) or u)
    shared = {u: v for u, v in own.items() if len(v) > 1}
    rm = plan(shared)
    print(f"1点もの {len(own)}本 / 2か所以上 {len(shared)}本 → 消す補URL {len(rm)}セル")
    for n, c, u in rm:
        r = rows[n - 1]
        print(f"  {n}行 {_col_letter(c)} itemID={_cell(r, 1) or '(出品待ち)'} {_cell(r, S.PRODUCT_COL_KEY)} | {u[-50:]}")
    if not write or not rm:
        print("(書いていない。--write で書く)" if rm else "✅ 共有は0件")
        return 0
    fresh = ws.get_all_values()
    ups, backup = [], []
    for n, c, u in rm:
        now = _cell(fresh[n - 1], c) if len(fresh) >= n else ""
        if now != _cell(rows[n - 1], c):
            print(f"  ⏭ {n}行 {_col_letter(c)} は読んだ後に変わった → 書かない")
            continue
        ups.append({"range": f"{_col_letter(c)}{n}", "values": [[""]]})
        backup.append({"row": n, "col": _col_letter(c), "itemID": _cell(fresh[n - 1], 1), "url": now})
    path = os.path.join(BACKUP_DIR, f"shared_supply_cleanup_{_dt.datetime.now():%Y%m%d_%H%M%S}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(backup, f, ensure_ascii=False, indent=1)
    if ups:
        ws.batch_update(ups, value_input_option="RAW")
    print(f"✅ {len(ups)}セル 消した (控え {path})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
