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
COL_PRICE = 5          # F列 商品価格 (メルカリの仕入値・円)
COL_KEY = 34           # AI列 KEY
COL_MARK = 37          # AL列 トレジャー (この道具が付ける印)

# ★2026-09-20 ユーザー「中間スプシに抽出されたデータで、トレジャーハント対象はどれか
#   分からないから、HIGHT にコピーできない」。**印を付けて仕分けできるようにする**。
#   値は3つだけ。◎ を絞って HIGH に写せばよい。
MARK_GO = "◎ 出せる"        # 売れ筋 かつ 仕入値が門を通る
MARK_HIGH = "△ 高い"        # 売れ筋だが仕入値が高すぎる (値下がりを待つ)
MARK_NONE = ""              # 売れ筋ではない (古い一覧で拾った分)

# 門 (ユーザー確定 2026-09-20)。厳しい方が効く。
#   安いカードは 1.5倍 が効いて締まり、高いカードは +7,000 が効いて締まる。
#   幅を持たせるのは 仕入元の値引き / ライバルの売り切れ / 補URLの入れ替え を見込むため。
CAP_ADD = 7000
CAP_MUL = 1.5
TARGETS = r"C:/dev/iMak_data/hq/market_sold/demand_market.csv"


def load_caps():
    """{product_id(大文字): 上限仕入れ値(円)} を売れ筋の一覧から読む (I/O)。

    ★値は HQ が eBay の実売中央値から pricing_engine で逆算した物。ここでは写すだけ。
    """
    import csv
    out = {}
    try:
        with open(TARGETS, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                pid = (r.get("product_id") or "").strip().upper()
                try:
                    v = int(r.get("上限仕入れ値(円)") or 0)
                except (TypeError, ValueError):
                    v = 0
                if pid and v:
                    out[pid] = v
    except Exception:                                          # noqa: BLE001
        return {}
    return out


def mark_of(price, cap):
    """その行に付ける印 (純関数)。cap が無ければ「売れ筋ではない」。"""
    if not cap:
        return MARK_NONE
    if not price:
        return MARK_HIGH                      # 値段が読めない = 出せない側に倒す
    return MARK_GO if (price <= cap + CAP_ADD and price <= cap * CAP_MUL) else MARK_HIGH


def plan(rows, conn, caps=None):
    """どの行に何を書くか決める (純関数寄り)。

    戻り: ({行番号: KEY}, 引けなかった数, {行番号: 印})。
    KEY の形は 商品管理シートと同じ `<category>:<product_id>` (例 pokemon_tcg:SV1V-105)。
    """
    import re as _re
    caps = caps if caps is not None else {}
    out, miss, marks = {}, 0, {}
    for i, r in enumerate(rows[1:], start=2):        # 1行目は見出し
        def g(k):
            return (r[k].strip() if len(r) > k else "")
        key = g(COL_KEY)
        if not key:
            title = g(COL_TITLE)
            no = CL.card_no(title)
            row = CL.lookup(CL.candidates(no, title), conn, title) if no else None
            if row:
                key = f"{row[3]}:{row[0]}"
                out[i] = key
            else:
                miss += 1
        pid = key.split(":")[-1].upper() if key else ""
        price = int(_re.sub(r"[^0-9]", "", g(COL_PRICE) or "0") or 0)
        marks[i] = mark_of(price, caps.get(pid))
    return out, miss, marks


def main(argv):
    write = "--write" in argv
    conn = sqlite3.connect(CL.DB)
    rows = S.read_tab(TAB, sheet_id=SHEET_ID)
    if not rows:
        print("シートが読めません")
        return 1
    caps = load_caps()
    if not caps:
        print("⚠ 売れ筋の一覧が読めません。先に market_ledger.py targets を実行してください")
        return 1
    got, miss, marks = plan(rows, conn, caps)
    import collections
    tally = collections.Counter(marks.values())
    print(f"{len(rows) - 1}件 — KEY を埋める {len(got)}件 / 引けない {miss}件")
    print(f"  ◎ 出せる     {tally.get(MARK_GO, 0):4}件  (売れ筋 かつ 仕入値が門を通る)")
    print(f"  △ 高い       {tally.get(MARK_HIGH, 0):4}件  (売れ筋だが高い。値下がり待ち)")
    print(f"  (印なし)     {tally.get(MARK_NONE, 0):4}件  (売れ筋ではない)")
    if not write:
        print("★ 書くなら --write を付けてください")
        return 0
    ws = S._open(SHEET_ID).worksheet(TAB)
    reqs = [{"range": f"AI{i}:AI{i}", "values": [[k]]} for i, k in got.items()]
    reqs += [{"range": "AL1:AL1", "values": [["トレジャー"]]}]
    reqs += [{"range": f"AL{i}:AL{i}", "values": [[m]]} for i, m in marks.items()]
    for n in range(0, len(reqs), 400):               # 一度に投げすぎない
        ws.batch_update(reqs[n:n + 400], value_input_option="RAW")
        print(f"  {min(n + 400, len(reqs))}/{len(reqs)} 行", flush=True)
    print(f"✅ KEY {len(got)}行 / 印 {len(marks)}行 を書きました")
    print("★ AL列「トレジャー」が ◎ の行を HIGH に写してください")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
