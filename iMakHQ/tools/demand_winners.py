#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""需要実証(売れ筋)リスト → 新規出品の指針。

死蔵を直すのでなく、需要シグナル(実売/WATCH/表示)が出ている『勝ち筋』を特定し、
同種を新規出品する判断材料を出す。eBay の自店データから『何を仕入れて出すべきか』を逆算。

スコア = 実売*10 + 90d販売*10 + WATCH*3 + impr*0.05  (実売 >> 興味(watch) > 露出)

入力: funnel CSV
出力: デスクトップ 需要実証リスト_YYYYMMDD.csv (商品別) + カテゴリ/ブランド別サマリー
"""
import csv
import datetime
import glob
import os
import re
import sys
from collections import defaultdict

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

DESK = r"C:\Users\imax2\OneDrive\デスクトップ"
FUNNEL_DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "funnel_output"))


def _f(v):
    try:
        return float(v)
    except (ValueError, TypeError):
        return 0.0


def demand_score(r):
    return (_f(r["sold_qty"]) + _f(r.get("sales90", 0))) * 10 + _f(r["watch"]) * 3 + _f(r["impr"]) * 0.05


def brand_key(title):
    """商品グループ判定 (新規出品の単位)。"""
    t = title.lower()
    if "porter" in t or "tanker" in t:
        return "PORTER (バッグ)"
    if "montbell" in t:
        return "Montbell (アウター)"
    if "g-shock" in t or "casio" in t:
        m = re.search(r"\b([A-Z]{2,3})[- ]?\d", title)
        return f"G-SHOCK {m.group(1)}系" if m else "G-SHOCK"
    if "psa 10" in t:
        if "one piece" in t: return "PSA10 One Piece"
        if "pokemon" in t: return "PSA10 Pokemon"
        if "dragon ball" in t: return "PSA10 Dragon Ball"
        if "gundam" in t: return "PSA10 Gundam"
        return "PSA10 TCG (他)"
    if "ichiban kuji" in t: return "一番くじ"
    if "s.h.figuarts" in t or "figuarts" in t: return "S.H.Figuarts"
    if "uniqlo" in t or " ut " in t or "t-shirt" in t: return "UNIQLO/Tシャツ"
    if any(k in t for k in ("sanrio", "kuromi", "hello kitty", "cinnamoroll")): return "Sanrio"
    if "anello" in t: return "Anello (バッグ)"
    if "reel" in t or "shimano" in t or "daiwa" in t: return "釣具リール"
    return "その他"


def main():
    fcsv = max(glob.glob(os.path.join(FUNNEL_DIR, "funnel_*.csv")), key=os.path.getmtime)
    rows = list(csv.DictReader(open(fcsv, encoding="utf-8")))
    for r in rows:
        r["score"] = round(demand_score(r), 1)
        r["group"] = brand_key(r["title"])
        try:
            r["instock"] = "在庫あり" if int(r["qty"]) != 0 else "在庫切れ"
        except (ValueError, KeyError):
            r["instock"] = "?"

    # 需要実証 = スコア>0 (= 実売 or watch or 表示 が有る)
    winners = sorted([r for r in rows if r["score"] > 0], key=lambda x: -x["score"])

    # 商品別リスト出力
    path = os.path.join(DESK, f"需要実証リスト_{datetime.date.today():%Y%m%d}.csv")
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["score", "group", "instock", "category", "price",
                                          "sold_qty", "sales90", "watch", "impr", "ctr", "title", "ebay_url"],
                           extrasaction="ignore")
        w.writeheader()
        for r in winners:
            w.writerow(r)

    # グループ別サマリー (= 新規出品で伸ばすべき単位)
    g = defaultdict(lambda: {"n": 0, "score": 0.0, "sold": 0, "watch": 0, "sold_listings": 0})
    for r in winners:
        d = g[r["group"]]
        d["n"] += 1; d["score"] += r["score"]
        d["sold"] += int(_f(r["sold_qty"]) + _f(r.get("sales90", 0)))
        d["watch"] += int(_f(r["watch"]))
        if _f(r["sold_qty"]) + _f(r.get("sales90", 0)) > 0:
            d["sold_listings"] += 1
    summary = sorted(g.items(), key=lambda kv: -kv[1]["score"])

    print(f"需要実証(スコア>0) listing: {len(winners)}件 / 全{len(rows)}件")
    print(f"\n=== 伸ばすべきグループ TOP (実売/watch/表示の合計スコア順) ===")
    print(f"  {'グループ':<22}{'件数':>5}{'実売':>5}{'watch':>7}{'売れ筋listing':>13}  スコア")
    for grp, d in summary[:15]:
        print(f"  {grp:<22}{d['n']:>5}{d['sold']:>5}{d['watch']:>7}{d['sold_listings']:>13}  {d['score']:.0f}")
    print(f"\n=== 個別 勝ち筋 TOP15 (新規出品で同種を狙う) ===")
    for r in winners[:15]:
        print(f"  [{r['group'][:16]:<16}] score{r['score']:>6} 実売{int(_f(r['sold_qty'])+_f(r.get('sales90',0)))} watch{r['watch']} {r['instock']} ${_f(r['price']):.0f}  {r['title'][:34]}")
    print(f"\nCSV出力: {path}")
    print("▶ 使い方: スコア上位グループ = 需要実証済 → 同種の新規商品を仕入れ・出品。")
    print("▶ '売れ筋listing数'が多いグループ = 単発でなく面で売れてる = 最優先で拡大。")


if __name__ == "__main__":
    main()
