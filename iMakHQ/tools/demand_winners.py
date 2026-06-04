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


def _first(t, kws):
    for kw in kws:
        if kw.lower().replace("-", "") in t.lower().replace("-", ""):
            return kw
    return None


def brand_key(title):
    """商品グループ判定 = フランチャイズ/サブライン粒度 (新規で『近しい商品』を仕入れる単位)。"""
    t = title.lower()
    if "uniqlo" in t or " ut " in t or "t-shirt" in t or "tshirt" in t:
        fr = _first(t, ["Dragon Ball", "Pokemon", "Demon Slayer", "Jujutsu", "One Piece", "Naruto",
                        "Evangelion", "Mario", "KAWS", "Haikyu", "Animal Crossing", "Hello Kitty",
                        "Chainsaw", "Spy x Family", "Gundam", "Attack on Titan", "Bleach", "Detective Conan", "Ado"])
        return f"UT × {fr}" if fr else "UT × その他"
    if "ichiban kuji" in t:
        fr = _first(t, ["Jujutsu", "Dragon Ball", "One Piece", "Hero Academia", "Gundam",
                        "Demon Slayer", "Naruto", "Pokemon", "Evangelion"])
        return f"一番くじ × {fr}" if fr else "一番くじ × 他"
    if "montbell" in t:
        ln = _first(t, ["Wind Blast", "Thunder Pass", "Plasma", "Permafrost", "EX Light", "Tachyon",
                        "Versalite", "Storm Cruiser", "Light Shell", "Rain Dancer"])
        return f"Montbell {ln}" if ln else "Montbell 他"
    if "porter" in t or "tanker" in t:
        return "PORTER Tanker" if "tanker" in t else "PORTER 他"
    if "g-shock" in t or "casio" in t:
        sub = _first(t, ["G-LIDE", "King of G", "Full Metal", "Mudmaster", "Frogman", "Gravitymaster",
                         "MR-G", "MT-G", "Rangeman", "Carbon Core", "G-STEEL", "G-SQUAD", "Mudman"])
        if sub:
            return f"G-SHOCK {sub}"
        m = re.search(r"\b([A-Z]{2,3})[- ]?\d", title)
        return f"G-SHOCK {m.group(1)}系" if m else "G-SHOCK 他"
    if "psa 10" in t:
        fr = _first(t, ["One Piece", "Pokemon", "Dragon Ball", "Gundam", "Yu-Gi", "Weiss", "Digimon"])
        return f"PSA10 {fr}" if fr else "PSA10 他"
    if "s.h.figuarts" in t or "figuarts" in t:
        fr = _first(t, ["Dragon Ball", "Kamen Rider", "One Piece", "Naruto", "Sailor Moon", "Demon Slayer", "Precure"])
        return f"Figuarts {fr}" if fr else "Figuarts 他"
    if any(k in t for k in ("sanrio", "kuromi", "hello kitty", "cinnamoroll", "pochacco")):
        return "Sanrio"
    if "anello" in t:
        return "Anello"
    if "reel" in t or "shimano" in t or "daiwa" in t:
        return "釣具リール"
    return "その他"


def feas(group):
    """近しい商品(同ライン/同フランチャイズの別商品)をタイムリーに調達できるか。
    ◎=定番継続容易 / △=可だが個別の市場/時期チェック要 / ✕=近しい品でも困難 / ?=個別。"""
    if group.startswith("G-SHOCK"):
        return ("◎", "同系の別型番を継続(Amazon/メルカリ)", "gshock_to_csv")
    if group.startswith("UT ×"):
        return ("◎", "同コラボ/新作UTを継続出品", "tshirt_listing")
    if group.startswith("Montbell"):
        return ("◎", "定番ラインを継続", "montbell_listing")
    if group.startswith("一番くじ"):
        return ("△", "同フランチャイズの新弾景品を都度", "ichibankuji_to_csv")
    if group.startswith("PORTER"):
        return ("△", "定番ラインの別色/別サイズ", "-")
    if group.startswith("PSA10"):
        return ("△", "同フランチャイズの別カードをメルカリ/スニダンで継続", "-")
    if group.startswith("Figuarts"):
        return ("△", "同フランチャイズの新作figureを都度", "-")
    return {"Sanrio": ("△", "供給は可だがUS需要低", "-"),
            "Anello": ("△", "供給は可だがUS需要低", "-"),
            "釣具リール": ("△", "同系の別型番を継続", "daiwa_jp/shimano_jp"),
            }.get(group, ("?", "個別判断", "-"))


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

    def verdict(mark, d):
        proven = d["sold_listings"] >= 2 or d["score"] >= 100
        if mark == "◎" and proven:
            return "★拡大推奨"
        if mark in ("◎", "△") and (d["sold_listings"] >= 1 or d["score"] >= 60):
            return "候補(要確認)"
        return "様子見"

    # グループ別サマリー CSV (新規出品の指針)
    gpath = os.path.join(DESK, f"新規出品強化_グループ別_{datetime.date.today():%Y%m%d}.csv")
    with open(gpath, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["グループ", "仕入れ適性", "件数", "実売", "watch", "売れ筋listing数", "スコア", "近しい商品の調達", "パイプライン", "判定"])
        for grp, d in summary:
            mark, reason, pipe = feas(grp)
            w.writerow([grp, mark, d["n"], d["sold"], d["watch"], d["sold_listings"],
                        f"{d['score']:.0f}", reason, pipe, verdict(mark, d)])

    print(f"需要実証(スコア>0) listing: {len(winners)}件 / 全{len(rows)}件")
    print(f"\n=== 新規出品強化: グループ別 (需要 × 近しい商品を出せるか) ===")
    print(f"  {'グループ':<20}{'適性':>4}{'件数':>5}{'実売':>5}{'watch':>6}{'スコア':>6}  判定")
    for grp, d in summary[:18]:
        mark, reason, pipe = feas(grp)
        print(f"  {grp:<20}{mark:>4}{d['n']:>5}{d['sold']:>5}{d['watch']:>6}{d['score']:>6.0f}  {verdict(mark, d)}")
    print(f"\n=== ★拡大推奨グループ (需要実証 × 近しい商品を継続調達◎) ===")
    for grp, d in summary:
        mark, reason, pipe = feas(grp)
        if verdict(mark, d) == "★拡大推奨":
            print(f"  {grp}: {reason} [{pipe}]  (実売{d['sold']}/watch{d['watch']}/売れ筋{d['sold_listings']}listing)")
    print(f"\nCSV出力: {path}")
    print(f"グループ別判定: {gpath}")
    print("▶ ★拡大推奨 = 需要実証 ∩ 近しい商品をタイムリーに出せる → 新規出品で面で増やす本命。")
    print("▶ △候補 = 需要はあるが個別の市場/時期チェックが要る (PSA は別カードの相場確認など)。")


if __name__ == "__main__":
    main()
