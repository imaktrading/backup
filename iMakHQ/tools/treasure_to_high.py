#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""トレジャーハントの候補 (中間スプシ `mercari_psa10_treasure`) を HIGH に「出品待ち」で足す。

    python iMakHQ/tools/treasure_to_high.py            # 何行足すか見るだけ
    python iMakHQ/tools/treasure_to_high.py --write    # HIGH に足して、中間スプシを緑に塗る
    python iMakHQ/tools/treasure_to_high.py --tab=chara [--write]   # キャラで拾った候補 (2026-09-24)

★2026-09-21 ユーザー確定「とりあえず、7マン以下は HIGH にコピーしたいね。重複があるなら除いて」
  「コピーしたら、色塗りして。重複も色塗り」。
  - 仕入値 (F列) が **会社の上限 7万円以下** の行だけ
  - HIGH に同じ仕入元 URL か 鑑定番号 が在る行は足さない (重複)。タブの中の重複も1行だけ
  - 足した行と、もともと HIGH に在った行を **緑** に塗る (緑 = HIGH にある行。harvest-targeting ③)

書く列 (psa_resource_gate.new_listing_rows_from_confirmed と同じ作り + PSA の新規分):
  A URL / C タイトル / D〜J (状態・F 仕入値・写真・説明・I 鑑定番号・J) / L ConditionID /
  R カテゴリ=TCG / S 色 / T サイズ / AC〜AG 補URL
★書かない列:
  B itemID (空 = まだ出していない = 出品くんが拾う) / K・M (HIGH では ポイント・現在価格。
  中間スプシの K・M は別の意味) / N・P (HIGH の数式) / **KEY** (未出品の行に KEY があると
  二重出品の守りが「出品済」と読んで止める。KEY は出品くんが判定した時に書く)
"""
from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sheet_io as S
import treasure_fill_key as T

COST_CAP = 70000
GREEN = {"red": 0.851, "green": 0.918, "blue": 0.827}      # #d9ead3
COPY_COLS = (0, 2, 3, 4, 5, 6, 7, 8, 9, 11, 18, 19, 28, 29, 30, 31, 32)
COL_CATEGORY = 17


def _g(r, i):
    return (r[i] if len(r) > i else "").strip()


def _price(s):
    return int(re.sub(r"[^\d]", "", s or "") or 0)


def plan(treasure_rows, high_rows, cap=COST_CAP):
    """どの行を足して、どの行を塗るか (純関数)。

    treasure_rows / high_rows: 見出しを除いた行 (list)。戻り: (足す[(シート行番号, 行)], 塗る行番号, 数)
    """
    hu = {_g(r, 0) for r in high_rows if _g(r, 0)}
    hc = {_g(r, 8) for r in high_rows if _g(r, 8)}
    add, paint, seen = [], [], set()
    n = {"over": 0, "noprice": 0, "in_high": 0, "dup_tab": 0}
    for i, r in enumerate(treasure_rows, start=2):
        url, cert, p = _g(r, 0), _g(r, 8), _price(_g(r, 5))
        if url in hu or (cert and cert in hc):
            n["in_high"] += 1
            paint.append(i)
            continue
        if not p:
            n["noprice"] += 1
            continue
        if p > cap:
            n["over"] += 1
            continue
        key = url or cert
        if key in seen:
            n["dup_tab"] += 1
            paint.append(i)
            continue
        seen.add(key)
        row = [""] * 39
        for c in COPY_COLS:
            row[c] = _g(r, c)
        row[COL_CATEGORY] = "TCG"
        add.append((i, row))
        paint.append(i)
    return add, paint, n


# ★2026-09-24: キャラで拾った候補 (抽出くんの `mercari_psa10_chara`) も同じ作りで HIGH に足せるようにする。
#   列は treasure と同じ。枠に入れる順は tcg_batch_select が「市場で売れた枚数」で決める
#   (キャラで広く拾い、売れるカードを先に出す。ユーザー確定 2026-09-24)
TABS = {"treasure": T.TAB, "chara": "mercari_psa10_chara"}


def tab_of(argv):
    """--tab=treasure|chara (既定 treasure) → 中間スプシのタブ名。知らない名前は止める。"""
    for a in argv:
        if a.startswith("--tab="):
            k = a.split("=", 1)[1]
            if k not in TABS:
                raise SystemExit(f"--tab は {'/'.join(TABS)} のどれか: {k}")
            return TABS[k]
    return TABS["treasure"]


def main(argv):
    import psa_hoju_fill as H
    tab = tab_of(argv)
    tr = S.read_tab(tab, sheet_id=T.SHEET_ID)[1:]
    if not tr:
        print(f"中間スプシ {tab} に行がありません")
        return 0
    hi = H._read_high()[1:]
    add, paint, n = plan(tr, hi)
    print(f"中間スプシ {len(tr)}行 → HIGH に足す {len(add)}行 / 塗る {len(paint)}行")
    print(f"  7万円超 {n['over']} / 値段が読めない {n['noprice']} / もう HIGH にある {n['in_high']} / "
          f"タブ内の重複 {n['dup_tab']}")
    if "--write" not in argv:
        print("★書くなら --write")
        return 0
    added = S.append_product_rows([r for _, r in add]) if add else 0
    # 確かめてから塗る: HIGH を読み直して、足した URL が本当に入ったか
    hi2 = {_g(r, 0) for r in H._read_high()[1:]}
    miss = [i for i, r in add if r[0] and r[0] not in hi2]
    ws = S._open(T.SHEET_ID).worksheet(tab)
    ok = [i for i in paint if i not in miss]
    last = S.col_letter(len(tr[0])) if hasattr(S, "col_letter") else "AL"
    reqs = [{"range": f"A{i}:{last}{i}", "format": {"backgroundColor": GREEN}} for i in ok]
    for k in range(0, len(reqs), 200):
        ws.batch_format(reqs[k:k + 200])
    print(f"HIGH に足した {added}行 / HIGH に見当たらない {len(miss)}行 / 緑に塗った {len(ok)}行")
    if miss:
        print("⚠️要対応: HIGH に入っていない行 (塗っていない):", miss[:20])
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
