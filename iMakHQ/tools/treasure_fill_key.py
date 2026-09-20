#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""トレジャーハントで集めた候補に **KEY を埋める**。

    python iMakHQ/tools/treasure_fill_key.py            # 何件埋まるか見るだけ
    python iMakHQ/tools/treasure_fill_key.py --write    # 実際に書く

★2026-09-20 ユーザー「KEY埋めて」。抽出くんが集めた 1,129件は KEY が全部 空で、
  そのままでは出品くんが「どのカードか」を判定できない。
  KEY を入れるのは **カタログを引くだけ** なので 出品くんの仕事
  (値を決めるのはカタログの仕事。ここでは写すだけ)。

★引き方は `catalog_lookup.py` が唯一の口。落とし穴と順番はあちらの docstring に書いてある。
★**引けなかった行は空のまま**にする。推測で入れると、別のカードとして出品することになる
  (出品の正確性原則: 判定不能は skip、破壊的動作に倒さない)。
"""
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import catalog_lookup as CL                                    # noqa: E402
import sheet_io as S                                           # noqa: E402

SHEET_ID = "1hTdFVGkni4Ih4kZGsBgiCKxpTlOeoO_wJdk8Ek5n41Q"
TAB = "mercari_psa10_treasure"
COL_TITLE = 2          # C列 タイトル
COL_KEY = 34           # AI列 KEY


def plan(rows, conn):
    """どの行に何を書くか決める (純関数寄り)。戻り: ({行番号(1始まり): KEY}, 引けなかった数)。

    KEY の形は 商品管理シートと同じ `<category>:<product_id>` (例 pokemon_tcg:SV1V-105)。
    """
    out, miss = {}, 0
    for i, r in enumerate(rows[1:], start=2):        # 1行目は見出し
        def g(k):
            return (r[k].strip() if len(r) > k else "")
        if g(COL_KEY):                               # 既に入っている物は触らない
            continue
        title = g(COL_TITLE)
        no = CL.card_no(title)
        row = CL.lookup(CL.candidates(no, title), conn, title) if no else None
        if row:
            out[i] = f"{row[3]}:{row[0]}"
        else:
            miss += 1
    return out, miss


def main(argv):
    write = "--write" in argv
    conn = sqlite3.connect(CL.DB)
    rows = S.read_tab(TAB, sheet_id=SHEET_ID)
    if not rows:
        print("シートが読めません")
        return 1
    got, miss = plan(rows, conn)
    print(f"{len(rows) - 1}件 — 引けた {len(got)}件 / 引けない {miss}件")
    if not write:
        for i, k in list(got.items())[:8]:
            print(f"  行{i:<5} {k}")
        print("★ 書くなら --write を付けてください")
        return 0
    import gspread                                             # noqa: F401
    sh = S._open(SHEET_ID)
    ws = sh.worksheet(TAB)
    col = "AI"
    reqs = [{"range": f"{col}{i}:{col}{i}", "values": [[k]]} for i, k in got.items()]
    for n in range(0, len(reqs), 400):               # 一度に投げすぎない
        ws.batch_update(reqs[n:n + 400], value_input_option="RAW")
        print(f"  {min(n + 400, len(reqs))}/{len(reqs)} 行", flush=True)
    print(f"✅ KEY を {len(reqs)}行に書きました (引けなかった {miss}行は空のまま)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
