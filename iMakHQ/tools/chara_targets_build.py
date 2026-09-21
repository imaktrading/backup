#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""キャラ軸の「探す先」を作る (2026-09-21).

2つの出どころを1本にまとめて `chara_market.csv` に出す。抽出くんはこれを読む。

  №2 市場のキャラ … テラピーク台帳 (他社がeBayで売った) で5枚以上売れたキャラ
  №3 うちのキャラ … うちが実際に売ったカードのキャラ (our_sold.csv・90日)

★**両方に出るキャラが一番強い** (市場でも売れていて、うちでも売れた)。
★キャラ軸に **カードごとの仕入上限は無い** (2026-09-21 ユーザー確定)。
  上限は会社の7万円のみ・値付けは cost-plus。だから「上限仕入れ値(円)」は空にする。

    python iMakHQ/tools/chara_targets_build.py
"""
from __future__ import annotations

import collections
import csv
import os
import sqlite3
import statistics as st
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import catalog_lookup as L
import chara_demand_xlsx as C

OUR_SOLD = r"C:/dev/iMak_data/hq/market_sold/our_sold.csv"
OUT = r"C:/dev/iMak_data/hq/market_sold/chara_market.csv"
MIN_SOLD_MARKET = 5          # 市場側の足切り (5枚以上)
# ★版の語を足す基準 (2026-09-21 ユーザー確定)。通常版が半分未満しか売れていないキャラは、
#   「PSA10 ルフィ」だけだと出品の多い通常版で 1語15件の枠が埋まり、売れる版に届かない。
#   キャラ名の語は残したまま「ルフィ プロモ」「ルフィ パラレル」を **足す** (減らさない)。
VERSION_WORDS = ("プロモ", "パラレル")
MIN_VERSION_SOLD = 3


def our_charas(path=OUR_SOLD):
    """うちが売ったカードのキャラ {キャラ: 枚数} (I/O)。

    ★カタログは `catalog_lookup` が唯一の口。番号は `card_no` で取ってから渡す
      (番号を渡さずに引くと 19件全部が「引けない」になる。2026-09-21 に踏んだ)。
    """
    conn = sqlite3.connect(L.DB)
    out = collections.Counter()
    try:
        rows = list(csv.DictReader(open(path, encoding="utf-8")))
    except FileNotFoundError:
        return out
    for r in rows:
        t = r.get("タイトル") or ""
        if "PSA" not in t.upper():
            continue                       # PSA10 以外 (UT / PORTER 等) は対象外
        try:
            n = int(float(r.get("売れた数") or 1))
        except ValueError:
            n = 1
        try:
            row = L.lookup(L.candidates(L.card_no(t), t), conn, t)
        except Exception:                                      # noqa: BLE001
            continue
        if row:
            name = (row[2] or row[1] or "").strip()
            if name:
                out[C.chara_of(name)] += n
    return out


def market_charas(min_sold=MIN_SOLD_MARKET):
    """市場 (テラピーク) で売れたキャラ {キャラ: 集計} (I/O)。"""
    rows = list(csv.DictReader(open(C.LEDGER, encoding="utf-8-sig")))
    conn = sqlite3.connect(C.CATALOG, uri=True)
    agg, _ = C.build(rows, conn)
    return {k: a for k, a in agg.items() if a["枚数"] >= min_sold}


def merge(market, ours):
    """2つの出どころを1本にする (純関数)。両方に出るキャラを先頭に置く。"""
    out = []
    for k in set(market) | set(ours):
        a = market.get(k)
        px = sorted(a["価格"]) if a else []
        out.append({
            "番号": "", "product_id": "", "和名": k, "英名": "", "画像": "",
            "ゲーム": (a or {}).get("ゲーム", "") or "",
            "売れた数": (a or {}).get("枚数", 0),
            "出品本数": (a or {}).get("カード数", 0),
            "実売中央値": round(st.median(px), 2) if px else "",
            "上限仕入れ値(円)": "",
            "市場のタイトル例": " / ".join((a or {}).get("例", [])),
            "うちの実績": ours.get(k, 0),
            "出どころ": ("市場+うち" if (a and k in ours) else ("市場" if a else "うち")),
        })
    # 両方に出る物 → うちの実績が多い物 → 市場で売れた物 の順
    out.sort(key=lambda r: (r["出どころ"] != "市場+うち", -r["うちの実績"], -r["売れた数"]))
    # 版の語は キャラ名の行のすぐ後ろに足す
    res = []
    for r in out:
        res.append(r)
        v = (market.get(r["和名"]) or {}).get("版") or {}
        tot = sum(v.values())
        if not tot or v.get("通常", 0) / tot >= 0.5:
            continue
        for word in VERSION_WORDS:
            if v.get(word, 0) >= MIN_VERSION_SOLD:
                res.append(dict(r, 和名=f"{r['和名']} {word}", 売れた数=v[word],
                                うちの実績=0, 市場のタイトル例=f"{word}だけで{v[word]}枚"))
    return res


def main():
    market, ours = market_charas(), our_charas()
    rows = merge(market, ours)
    with open(OUT, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    both = [r for r in rows if r["出どころ"] == "市場+うち"]
    print(f"キャラ {len(rows)}種類 → {OUT}")
    print(f"  市場+うち (両方で売れた) : {len(both):3d}キャラ  ← 一番強い")
    print(f"  市場だけ                 : {len([r for r in rows if r['出どころ']=='市場']):3d}キャラ")
    print(f"  うちだけ                 : {len([r for r in rows if r['出どころ']=='うち']):3d}キャラ")
    print()
    print("先頭12キャラ (これが検索語になる)")
    for i, r in enumerate(rows[:12], 1):
        print(f"  {i:2d}. PSA10 {r['和名']:20s} 市場{r['売れた数']:3d}枚 / うち{r['うちの実績']}枚 [{r['出どころ']}]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
