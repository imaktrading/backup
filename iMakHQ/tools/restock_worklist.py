#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A: RESTOCK 再仕入れワークシート — 在庫切れ「だが需要実証済」(RESTOCK)を、
仕入れ先(メルカリ)再確保のための1枚にまとめる。

設計思想 (2026-06-05):
  在庫切れ1992件のうち、ファネルが「需要実証済(過去販売 or watcher 有)」と仕分けた
  RESTOCK だけを攻める。さらに **US 出品分に限定** (US=売上半分/高AOV=実需の本丸。
  同一SKUは4サイト同時出品なので US 起点で再仕入れすれば全サイトで復活する。US にすら
  出してない=非US watcher だけの商品は優先度最低なので除外)。
  商品ごとに需要・eBay URL・メルカリ検索URL・GO/NO列を出す。
  **自動仕入れはしない** (Precision 100%原則: 人がメルカリで現物が同一か確認して GO/NO)。
  メルカリ検索キーワード:
    - G-SHOCK : 型番 (タイトルから抽出。型番=完全一致で確実)
    - 他vein  : demand_winners の facet seed (モンベル/PORTER タンカー/一番くじ/PSA10 等 JP寄り)
    - fallback: タイトルから定型句を除いた語

入力 : ../funnel_output/funnel_*.csv (RESTOCK flag)
出力 : デスクトップ 在庫切れ再仕入れ_YYYYMMDD.csv (需要大きい順) + コンソール要約
"""
import csv
import datetime
import glob
import importlib.util
import os
import re
import sys
from collections import defaultdict

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

_HERE = os.path.dirname(os.path.abspath(__file__))
FUNNEL_DIR = os.path.normpath(os.path.join(_HERE, "..", "funnel_output"))
DESK = r"C:\Users\imax2\OneDrive\デスクトップ"

# demand_winners を import (vein_of / facets / mercari_url を再利用)
_spec = importlib.util.spec_from_file_location("demand_winners", os.path.join(_HERE, "demand_winners.py"))
dw = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dw)

_MODEL_RE = re.compile(r"[A-Z]{2,4}-[A-Z0-9]{2,}(?:-[A-Z0-9]+)*")
# メルカリ検索の邪魔になる eBay 定型句 (fallback キーワード生成時に除去)
_BOILER = re.compile(
    r"\b(Pre-?owned|Used|New|NWT|NIB|Japan|Genuine|Authentic|Men's|Women's|Unisex|"
    r"US|JP|Size|Brand New|with Tags|Free Shipping|Fast Shipping|F/S)\b|"
    r"\(.*?\)|US\s*[SML0-9X]+|JP\s*[SML0-9X]+", re.I)


def _f(v):
    try:
        return float(str(v).replace(",", "").replace("$", "").strip())
    except (ValueError, TypeError):
        return 0.0


def _clean_title(title):
    t = _BOILER.sub(" ", title or "")
    t = re.sub(r"\s+", " ", t).strip()
    return t[:60] or (title or "")


def mercari_kw(vein, title):
    """vein 別に「メルカリで現物を探す」検索キーワードを決める。"""
    if vein == "G-SHOCK":
        m = _MODEL_RE.search(title or "")
        if m:
            return m.group(0)
    for _dim, _val, seed in dw.facets(vein, title or ""):
        if seed:
            return seed
    return _clean_title(title)


def load_restock():
    fs = glob.glob(os.path.join(FUNNEL_DIR, "funnel_*.csv"))
    if not fs:
        sys.exit("funnel_*.csv がありません。先に『📊 ファネル分析』を実行してください。")
    rows = list(csv.DictReader(open(max(fs, key=os.path.getmtime), encoding="utf-8")))
    return [r for r in rows if "RESTOCK" in (r.get("flags") or "").split("|")]


def keep_us(rs):
    """US 出品行のみ残す。US=実需の本丸(売上半分/高AOV)で、再仕入れすれば同一SKUは
    全サイトで復活する。US にすら出してない=非US watcher だけの商品は優先度最低なので除外。
    戻り: (us_rows, 除外した商品数)。"""
    all_t = {(r.get("title") or "").lower() for r in rs}
    us = [r for r in rs if (r.get("site") or "") == "US"]
    us_t = {(r.get("title") or "").lower() for r in us}
    return us, len(all_t - us_t)


def dedup_by_title(rows):
    """同一商品(title)が複数サイトに在る → 1商品に集約。需要は合算、サイト列挙。"""
    agg = {}
    for r in rows:
        title = (r.get("title") or "").strip()
        if not title:
            continue
        k = title.lower()
        d = agg.get(k)
        if d is None:
            d = agg[k] = {
                "title": title, "vein": dw.vein_of(title), "sold": 0.0, "watch": 0.0,
                "sites": set(), "price": 0.0, "item_id": r.get("item_id", ""),
                "ebay_url": r.get("ebay_url", ""),
            }
        d["sold"] += _f(r.get("sold_qty")) + _f(r.get("sales90"))
        d["watch"] += _f(r.get("watch"))
        d["price"] = max(d["price"], _f(r.get("price")))
        if r.get("site"):
            d["sites"].add(r["site"])
    return list(agg.values())


def main():
    us_rows, dropped = keep_us(load_restock())
    items = dedup_by_title(us_rows)
    for d in items:
        d["demand"] = d["sold"] * 100 + d["watch"] * 8
    items.sort(key=lambda d: -d["demand"])

    stamp = datetime.date.today().strftime("%Y%m%d")
    path = os.path.join(DESK, f"在庫切れ再仕入れ_{stamp}.csv")
    base, ext = os.path.splitext(path)
    for i in range(20):
        try:
            f = open(path if i == 0 else f"{base}_{i+1}{ext}", "w", newline="", encoding="utf-8-sig")
            path = f.name
            break
        except PermissionError:
            continue
    with f:
        w = csv.writer(f)
        w.writerow(["GO/NO", "系統", "商品名", "実売", "watch", "サイト", "価格",
                    "メルカリ検索URL", "メルカリ検索語", "eBay URL"])
        for d in items:
            kw = mercari_kw(d["vein"], d["title"])
            w.writerow(["", d["vein"], d["title"], int(d["sold"]), int(d["watch"]),
                        "/".join(sorted(d["sites"])), f"${d['price']:.0f}",
                        dw.mercari_url(kw), kw, d["ebay_url"]])

    by_vein = defaultdict(lambda: {"n": 0, "sold": 0.0, "watch": 0.0})
    for d in items:
        v = by_vein[d["vein"]]
        v["n"] += 1
        v["sold"] += d["sold"]
        v["watch"] += d["watch"]
    print(f"RESTOCK 再仕入れ候補 (US出品のみ) = 在庫切れ ∩ 需要実証済 = {len(items)}商品")
    if dropped:
        print(f"  ※ US未出品(非US watcherのみ)で除外 = {dropped}商品 (再仕入れ優先度 最低)")
    print(f"  {'系統':<12}{'商品数':>6}{'実売':>6}{'watch':>7}")
    for v, x in sorted(by_vein.items(), key=lambda kv: -kv[1]["n"]):
        print(f"  {v:<12}{x['n']:>6}{int(x['sold']):>6}{int(x['watch']):>7}")
    print(f"\nCSV出力: {path}")
    print("▶ 各行のメルカリ検索URLを開き、現物が同一か確認 → GO/NO列を埋める (自動仕入れはしない)")
    print("▶ G-SHOCK は型番=完全一致で確実。他vein はカテゴリ寄せ検索なので現物照合必須。")


if __name__ == "__main__":
    main()
