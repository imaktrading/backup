# -*- coding: utf-8 -*-
"""テラピーク台帳 → カード単位の需要表を作る (2026-09-21).

今まで `demand_market.csv` は **2枚以上売れた83枚**しか持っていなかった。
台帳 (`market_sold/ledger.csv`) には 日本セラーの PSA10 が90日で売れた分がほぼ全数
入っており、番号が読めるカードは **676種類**ある。市場の1割しか見ずに門を判定していた。

出力: `market_sold/demand_full.csv`
  番号 / 売れた枚数 / 出品者数 / 実売中央 / 実売最安 / 実売最高 / 価格分散 /
  最終落札日 / ゲーム / 代表タイトル

列の意味 (Gemini 相談 2026-09-20 で確定した門に対応):
  - **実売最高** … 門0「この値段を超えて出さない」。実測で今の在庫の70%が違反していた
  - **出品者数** … 門2「需給が締まっているか」。ACTIVE を API で引かなくても近似できる
  - **価格分散** … 門3「最安でなくても買われる市場か」(最高÷最安 ≥ 1.35)
"""
from __future__ import annotations

import collections
import csv
import os
import re
import statistics as st
import sys

LEDGER = r"C:/dev/iMak_data/hq/market_sold/ledger.csv"
OUT = r"C:/dev/iMak_data/hq/market_sold/demand_full.csv"

_NUM = re.compile(r"\b(\d{2,3}/\d{2,3}|[A-Z]{1,3}\d{0,2}-\d{2,3}|\d{3}/[A-Z]-P)\b")


def card_numbers(title):
    """タイトルから カード番号 を取る (純関数)。複数入っていれば全部返す。"""
    return sorted({x.upper() for x in _NUM.findall(title or "")})


def to_num(x):
    try:
        return float(str(x).replace(",", "").replace("$", "").strip() or 0)
    except ValueError:
        return 0.0


def game_of(title):
    t = (title or "").lower()
    if "one piece" in t:
        return "one_piece_tcg"
    if "dragon ball" in t or "dragonball" in t:
        return "dragonball_scg"
    return "pokemon_tcg"


def build(rows):
    """台帳の行 → {番号: 集計} (純関数・test可)。"""
    qty = collections.Counter()
    px = collections.defaultdict(list)
    lots = collections.defaultdict(set)
    last = {}
    title = {}
    for r in rows:
        t = r.get("タイトル") or ""
        p = to_num(r.get("平均落札"))
        for k in card_numbers(t):
            qty[k] += to_num(r.get("売れた数"))
            lots[k].add(r.get("itemId") or t)
            if p > 0:
                px[k].append(p)
            title.setdefault(k, t)
            d = (r.get("最終落札日") or "").strip()
            if d and d > last.get(k, ""):
                last[k] = d
    out = []
    for k, q in qty.items():
        v = sorted(px.get(k) or [])
        out.append({
            "番号": k,
            "売れた枚数": int(q),
            "出品者数": len(lots[k]),
            "実売中央": round(st.median(v), 2) if v else "",
            "実売最安": v[0] if v else "",
            "実売最高": v[-1] if v else "",
            "価格分散": round(v[-1] / v[0], 2) if (v and v[0] > 0) else "",
            "最終落札日": last.get(k, ""),
            "ゲーム": game_of(title.get(k, "")),
            "代表タイトル": (title.get(k) or "")[:70],
        })
    out.sort(key=lambda r: (-r["売れた枚数"], r["番号"]))
    return out


def main():
    rows = list(csv.DictReader(open(LEDGER, encoding="utf-8-sig")))
    out = build(rows)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, list(out[0]))
        w.writeheader()
        w.writerows(out)
    n2 = len([r for r in out if r["売れた枚数"] >= 2])
    print("台帳 %d行 → カード %d種類 (2枚以上 %d種類)" % (len(rows), len(out), n2))
    print("  出品者1人だけのカード: %d種類" % len([r for r in out if r["出品者数"] == 1]))
    print("  価格分散 1.35倍以上   : %d種類"
          % len([r for r in out if r["価格分散"] != "" and r["価格分散"] >= 1.35]))
    print("出力:", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
