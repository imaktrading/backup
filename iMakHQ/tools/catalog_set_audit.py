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
import os
import re
import sqlite3
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

DB = r"C:\dev\iMak_data\catalog\products.sqlite"

# ============================================================================
# 契約 v1.2 (2026-08-10 co-sign): set 整合の SSOT は iMakCatalog/set_reference.py に移設。
# ここでは audit CLI / 内部 audit() のみ保持。set_total_reference / row_set_issue /
# eb_era / card_total / ERA_YEARS は catalog helper から re-export する
# (HQ 内他モジュールが古い import path で壊れないよう互換用の shim を残す)。
# ============================================================================
_CATALOG = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                          "..", "..", "iMakCatalog"))
if _CATALOG not in sys.path:
    sys.path.insert(0, _CATALOG)
from set_reference import (  # noqa: E402
    ERA_YEARS,
    _KNOWN_MULTI_TOTAL_OK,
    card_total,
    eb_era,
    row_set_issue,
    set_total_reference,
)


def _is_excluded_pid(pid):
    """[3] 整合チェックから除外する不正 product_id (= set_name_ebay 以前の別案件)。

    'cardID...' は product_id 自体が不正なレコードで、total 整合の対象外
    (= set誤マップでなく product_id 不正。別途 product_id 調査案件)。
    """
    return (pid or "").startswith("cardID")


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
        # 3) total収集 (同一set内の複数total検出用)。不正product_id(cardID)は除外。
        tot = str(sp.get("card_number_total", "")).strip()
        if tot and not _is_excluded_pid(pid):
            set_totals[eb][tot] += 1
            set_pids[eb][tot].append(pid.split("-")[0])
    # 3) 同一 set_name_ebay に複数 card_number_total が混在 = 誤マップ (1セット=1total が原則)。
    #    ただし verified-legit な多total (_KNOWN_MULTI_TOTAL_OK) は除外 (異なるJPセットの公式EN同名等)。
    total_viol = []
    for eb, tots in set_totals.items():
        if eb in _KNOWN_MULTI_TOTAL_OK:
            continue
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
