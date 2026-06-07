#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""カタログ set_name_ebay 内部整合監査 (read-only)。

2026-06-07 buyer指摘(set_name_ebay 誤り)を受け、「出品後に発覚」を防ぐための自己検査。
外部データ不要の内部矛盾を検出:
  1. 世代不一致: product_id の世代 ≠ set_name_ebay の世代 (例 M3-* なのに Sun & Moon—)
  2. 年不一致  : Year Manufactured が set_name_ebay 世代の年代レンジ外 (例 set=Sun&Moon(2017-19) で year=2026)
これは check_csv の出品時ゲートにも組込む想定 (fail-closed: 矛盾は出品ブロック)。
"""
import json
import re
import sqlite3
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

DB = r"C:\dev\iMak_data\catalog\products.sqlite"

# set_name_ebay の世代プレフィックス → 妥当な発売年レンジ
ERA_YEARS = {
    "Black & White": (2011, 2014),
    "XY": (2013, 2017),
    "Sun & Moon": (2017, 2020),
    "Sword & Shield": (2019, 2023),
    "Scarlet & Violet": (2022, 2026),
}


def pid_era(pid):
    """product_id プレフィックス → 世代。"""
    if re.match(r"^(DP|Pt|DPt|L\d|LL|HS)", pid):
        return "Legacy(DP/HGSS)"
    if re.match(r"^BW", pid):
        return "Black & White"
    if re.match(r"^XY", pid):
        return "XY"
    if re.match(r"^SM", pid):
        return "Sun & Moon"
    if re.match(r"^SV", pid):
        return "Scarlet & Violet"
    if re.match(r"^M\d", pid):
        return "MEGA"
    if re.match(r"^S\d", pid):
        return "Sword & Shield"
    return "?"


def eb_era(eb):
    """set_name_ebay → 世代 (prefix から)。"""
    for era in ("Black & White", "XY", "Sun & Moon", "Sword & Shield", "Scarlet & Violet"):
        if eb.startswith(era):
            return era
    return "bare/other"


def audit(db=DB):
    import collections
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    era_viol, year_viol = [], []
    # set_name_ebay → {card_number_total: 件数} (同一setに複数totalが混在=誤マップ検出用)
    set_totals = collections.defaultdict(collections.Counter)
    set_pids = collections.defaultdict(lambda: collections.defaultdict(list))
    for r in con.execute("SELECT product_id,set_name,specs FROM products WHERE category='pokemon_tcg'"):
        pid = r["product_id"] or ""
        try:
            sp = json.loads(r["specs"]) if r["specs"] else {}
        except Exception:
            sp = {}
        eb = sp.get("set_name_ebay", "")
        if not eb:
            continue
        pe, ee = pid_era(pid), eb_era(eb)
        # 1) 世代不一致 (両方判定でき、MEGA/bare/?を除く)
        if pe not in ("?", "MEGA") and ee != "bare/other" and pe != ee:
            era_viol.append((pid, r["set_name"], eb, pe, ee))
        # 2) 年不一致
        yr = sp.get("year_manufactured") or sp.get("Year Manufactured") or ""
        m = re.search(r"(20\d\d)", str(yr))
        if m and ee in ERA_YEARS:
            y = int(m.group(1)); lo, hi = ERA_YEARS[ee]
            if not (lo <= y <= hi):
                year_viol.append((pid, eb, y, ee, (lo, hi)))
        # 3) total収集 (同一set内の複数total検出用)
        tot = str(sp.get("card_number_total", "")).strip()
        if tot:
            set_totals[eb][tot] += 1
            set_pids[eb][tot].append(pid.split("-")[0])
    # 3) 同一 set_name_ebay に複数 card_number_total が混在 = 誤マップ (1セット=1total が原則)
    total_viol = []
    for eb, tots in set_totals.items():
        if len(tots) > 1:
            # 最多totalを正、少数派を誤マップ候補
            major = tots.most_common(1)[0][0]
            for t, n in tots.items():
                if t != major:
                    prefs = sorted(set(set_pids[eb][t]))
                    total_viol.append((eb, t, n, major, prefs))
    return era_viol, year_viol, total_viol


def main():
    era_viol, year_viol, total_viol = audit()
    import collections
    print("=== カタログ set_name_ebay 内部整合監査 ===")
    print(f"\n[1] 世代不一致 (product_id世代 ≠ set名世代): {len(era_viol)}件")
    by = collections.Counter((v[3], v[4], v[0].split('-')[0]) for v in era_viol)
    for (pe, ee, pref), n in by.most_common(20):
        print(f"  {pref:8} {n:3}件  {pe} → 誤set世代 {ee}")
    print(f"\n[2] 年不一致 (Year が set世代の年代外): {len(year_viol)}件")
    for (pid, eb, y, ee, rng) in year_viol[:10]:
        print(f"  {pid:10} year={y} vs {ee}{rng}")
    print(f"\n[3] 同一set内に複数total混在 (=同世代内の誤マップ): {len(total_viol)}組")
    for eb, t, n, major, prefs in sorted(total_viol, key=lambda x: -x[2])[:20]:
        print(f"  set='{eb[:30]:30}' に /{t}({n}件,{prefs}) 混在 (主流/{major}) ← /{t}が誤マップ疑い")
    return era_viol, year_viol, total_viol


if __name__ == "__main__":
    main()
