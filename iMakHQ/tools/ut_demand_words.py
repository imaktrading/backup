#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""UT の「次に集める作品」を、売れ行きから決める (2026-09-12)。

設計 iMakHQ/UT_FLOW.md の ⑫ (需要の還流)。
抽出くんは今、カタログの **公式売り切れコラボ名** を上から20語で探している (件数順)。
そこに **eBay で実際に動いた作品** の順位を渡し、売れる物から集めてもらう。

数え方 (ファネルの UT 出品だけ):
    売れた数 (生涯 + 90日) × 3 + ウォッチ + 表示があったか
  作品は **出品タイトルの英語名** で判定し (`ut_title_names.yaml` の値)、
  カタログの日本語のコラボ名に戻して渡す (抽出くんはメルカリを日本語で探すため)。

出力: C:/dev/iMak_data/harvest/ut_demand_words.json
    [{"work_en", "collab_jp", "score", "sold", "watch", "listings", "oos"} …] 点数の高い順
"""
from __future__ import annotations

import argparse
import collections
import csv
import glob
import json
import os
import sqlite3
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, r"C:\dev\iMak\iMakMercari")

FUNNEL_DIR = os.path.normpath(os.path.join(_HERE, "..", "funnel_output"))
OUT_PATH = r"C:/dev/iMak_data/harvest/ut_demand_words.json"
DB_PATH = r"C:/dev/iMak_data/catalog/products.sqlite"


def _i(v):
    try:
        return int(float(str(v).strip() or 0))
    except (TypeError, ValueError):
        return 0


def is_ut(title):
    """その出品が UNIQLO/GU の T シャツか (純関数)。"""
    t = (title or "").upper()
    return "UNIQLO" in t or " UT " in t or t.startswith("UT ")


def score_rows(rows, works, title_has):
    """ファネルの行 → {作品の英語名: {score, sold, watch, listings, oos}} (純関数)。

    ★売れた数だけだと数が少なすぎて順位が付かない (実測 2026-09-08: UT 164出品で売上 8)。
      ウォッチと表示も足して「見られている物」を拾う。
    """
    names = sorted(set(works.values()), key=len, reverse=True)
    out = collections.defaultdict(lambda: {"score": 0, "sold": 0, "watch": 0,
                                           "listings": 0, "oos": 0})
    for r in rows:
        if not is_ut(r.get("title")):
            continue
        w = next((n for n in names if title_has(r.get("title"), n)), "")
        if not w:
            continue
        sold = _i(r.get("sold_qty")) + _i(r.get("sales90"))
        watch = _i(r.get("watch"))
        seen = 1 if (_i(r.get("impr")) or _i(r.get("impr_total"))) else 0
        d = out[w]
        d["sold"] += sold
        d["watch"] += watch
        d["listings"] += 1
        d["oos"] += 1 if _i(r.get("qty")) == 0 else 0
        d["score"] += sold * 3 + watch + seen
    return dict(out)


def collab_jp_for(work_en, works, catalog_collabs):
    """英語の作品名 → カタログで使われている日本語のコラボ名 (無ければ "")。純関数。

    表 (日本語→英語) を逆に引き、**カタログに実在する書き方**を選ぶ
    (抽出くんはこの語でメルカリを探すので、カタログに無い書き方を渡さない)。
    """
    jp = [k for k, v in works.items() if v == work_en and not k.isascii()]
    hit = [k for k in jp if k in catalog_collabs]
    return (hit or jp or [""])[0]


def catalog_collabs(db=DB_PATH):
    """カタログに実在するコラボ名 (公式で売り切れている Tシャツの分だけ)。"""
    con = sqlite3.connect(db)
    out = set()
    try:
        for (specs,) in con.execute("select specs from products where category in ('uniqlo_ut','gu')"):
            try:
                s = json.loads(specs or "{}")
            except ValueError:
                continue
            if s.get("not_tee") or s.get("in_stock") is True:
                continue
            c = (s.get("collab") or "").strip()
            if c and c != "その他":
                out.add(c)
    finally:
        con.close()
    return out


def latest_funnel():
    fs = glob.glob(os.path.join(FUNNEL_DIR, "funnel_*.csv"))
    return max(fs, key=os.path.getmtime) if fs else ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="抽出くんに渡すファイルを書く")
    ap.add_argument("--top", type=int, default=20)
    a = ap.parse_args()
    import ut_catalog_values as V
    src = latest_funnel()
    if not src:
        print("funnel_*.csv がありません (先に 📊 ファネル分析)")
        return 1
    with open(src, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    works = V.load_works()
    scored = score_rows(rows, works, V.title_has)
    cc = catalog_collabs()
    out = []
    for w, d in sorted(scored.items(), key=lambda x: (-x[1]["score"], x[0])):
        out.append({"work_en": w, "collab_jp": collab_jp_for(w, works, cc), **d})
    print(f"元: {os.path.basename(src)} / UT の出品 {sum(d['listings'] for d in scored.values())}件"
          f" / 作品 {len(out)}")
    for r in out[:a.top]:
        print(f"  {r['score']:4d}  {r['work_en']:<22} {r['collab_jp']:<12} "
              f"売れた{r['sold']} ウォッチ{r['watch']} 出品{r['listings']} (在庫切れ{r['oos']})")
    if not a.write:
        print("\n→ 抽出くんに渡すには --write")
        return 0
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    tmp = OUT_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"src": os.path.basename(src), "works": out}, f, ensure_ascii=False, indent=1)
    os.replace(tmp, OUT_PATH)
    print(f"\n✅ {OUT_PATH} に書きました ({len(out)}作品)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
