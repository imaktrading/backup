#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""① 効果測定ループ — funnel 世代間 diff で「直した結果が効いたか」を測る。

既存メンテの PDCA を閉じる最後のピース。直近2世代の funnel_*.csv を突合し、
「前回 直す対象だった listing が、今回どう動いたか」をコホート別に出す。

打ち手 ↔ コホートの対応:
  - 取下再出品(RELIST=NO_SEARCH+NO_CLICK) → 今回その listing は バケツを抜けたか / まだ詰まってるか /
    relist された(item_id 変化=新規) か / 消えた(End/売れ)か
  - ✏️タイトル改修(NO_CLICK)            → CTR が上がったか / NO_CLICK を抜けたか
  - 💲価格抵抗(NO_CONVERT)               → 売れたか / 値下げされたか / NO_CONVERT を抜けたか

突合のキー (relist で item_id **も title も** 変わる点に対応):
  1. item_id 一致 = in-place (値下げ・タイトル in-place revise・据え置き)
  2. item_id 消滅 & 同 supply_url(=仕入元URL) が新 item_id で再出現 = **取下再出品された** 個体
     (relist は出品くんが title を再生成するので title 突合は破綻する。仕入元URL は不変なのでこれを使う。
      supply_url は listing_funnel が生成時にスプシ A列から焼き込む。旧世代CSVに無ければ relist 追跡不可)
  3. どちらも無し = End / 売れ切れ / CULL で消えた

⚠ 正直な注意 (誤読防止):
  - **世代間が短い**(数日)と eBay の impression 蓄積が追いつかず露出系は誤差。間隔(日)を明示する。
  - **判定方式が違う世代どうし**(片方が PL累計=promo-aware、片方が organic-only=旧)は、
    バケツ移動が「打ち手の効果」でなく「分類ロジック変更」で起きる。基準差を検出したら警告し、
    バケツ移動を効果と解釈しないよう明示する(2026-06-04→06-05 がまさにこのケース)。

入力 : ../funnel_output/funnel_*.csv (直近2世代を自動選択。--old / --new で明示も可)
出力 : デスクトップ 効果測定_<old>_to_<new>.csv (per-item の old/new と判定) + コンソール要約
"""
import argparse
import csv
import datetime
import glob
import importlib.util
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

_HERE = os.path.dirname(os.path.abspath(__file__))
FUNNEL_DIR = os.path.normpath(os.path.join(_HERE, "..", "funnel_output"))
DESK = r"C:\Users\imax2\OneDrive\デスクトップ"

_spec = importlib.util.spec_from_file_location("demand_winners", os.path.join(_HERE, "demand_winners.py"))
dw = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dw)

# 直す対象だったコホート (前世代でこの flag を持つ listing を追跡)
FIX_BUCKETS = ("NO_SEARCH", "NO_CLICK", "NO_CONVERT", "OVERPRICED")


def _f(v):
    try:
        return float(str(v).replace(",", "").replace("$", "").strip())
    except (ValueError, TypeError):
        return 0.0


def _flags(r):
    return set(f for f in (r.get("flags") or "").split("|") if f)


def load(path):
    return list(csv.DictReader(open(path, encoding="utf-8")))


def date_of(path):
    m = re.search(r"funnel_(\d{8})", os.path.basename(path))
    return m.group(1) if m else os.path.basename(path)


def pl_based(rows):
    """この世代が PL累計(promo-aware)で分類されたか。impr_total に非ゼロがあれば True。"""
    return any(_f(r.get("impr_total")) > 0 for r in rows)


def exposure(r, use_total):
    """露出指標。promo-aware 世代は impr_total、旧世代は organic impr。"""
    return _f(r.get("impr_total")) if use_total else _f(r.get("impr"))


def sold_of(r):
    return _f(r.get("sold_qty")) + _f(r.get("sales90"))


def match_new(old_row, new_by_id, new_by_supply):
    """old_row の追跡先を new 世代から返す → (new_row, 状態)。
    in-place / relisted(新id・同仕入元URL) / gone を判定。
    relist は title も変わるので title では突合しない。仕入元URL(不変)のみで relist を追う。"""
    iid = old_row["item_id"]
    if iid in new_by_id:
        return new_by_id[iid], "in_place"
    su = (old_row.get("supply_url") or "").strip()
    if su:
        cand = new_by_supply.get(su)
        if cand and cand["item_id"] != iid:
            return cand, "relisted"   # item_id 変化 & 同仕入元URL = 取下再出品された個体
    return None, "gone"


def verdict(old_row, new_row, state, comparable):
    """1個体の判定。state=gone はここに来ない。
    comparable=False(基準差あり) のときバケツ移動は効果と見なさない。"""
    old_b = _flags(old_row) & set(FIX_BUCKETS)
    new_b = _flags(new_row) & set(FIX_BUCKETS)
    sold_gain = sold_of(new_row) - sold_of(old_row)
    if sold_gain > 0:
        return "SOLD", sold_gain
    if not comparable:
        return "基準差(判定不能)", 0
    left = old_b - new_b
    stayed = old_b & new_b
    if left and not stayed:
        return "改善(バケツ脱出)", 0
    if stayed:
        return "停滞(同バケツ残)", 0
    return "悪化/横ばい", 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--old", default=None, help="前世代 funnel CSV (既定=2番目に新しい)")
    ap.add_argument("--new", default=None, help="今世代 funnel CSV (既定=最新)")
    args = ap.parse_args()

    if args.old and args.new:
        f_old, f_new = args.old, args.new
    else:
        fs = sorted(glob.glob(os.path.join(FUNNEL_DIR, "funnel_*.csv")), key=os.path.getmtime)
        if len(fs) < 2:
            sys.exit("funnel_*.csv が2世代以上ありません。『📊 ファネル分析』を別日に2回以上実行してください。")
        f_old, f_new = fs[-2], fs[-1]

    old_rows, new_rows = load(f_old), load(f_new)
    d_old, d_new = date_of(f_old), date_of(f_new)
    old_by_id = {r["item_id"]: r for r in old_rows}
    new_by_id = {r["item_id"]: r for r in new_rows}
    # 仕入元URL → row (新世代側。relist で item_id が変わった個体を不変キーで追う)
    new_by_supply = {}
    for r in new_rows:
        su = (r.get("supply_url") or "").strip()
        if su:
            new_by_supply.setdefault(su, r)
    old_has_su = sum(1 for r in old_rows if (r.get("supply_url") or "").strip())

    # 世代間隔と判定方式の整合をチェック (誤読防止の核)
    try:
        interval = (datetime.datetime.strptime(d_new, "%Y%m%d")
                    - datetime.datetime.strptime(d_old, "%Y%m%d")).days
    except ValueError:
        interval = None
    pl_old, pl_new = pl_based(old_rows), pl_based(new_rows)
    comparable = (pl_old == pl_new)   # 同じ露出基準どうしのみバケツ移動を効果と見なせる

    print(f"効果測定ループ: {d_old} → {d_new}" + (f"  (間隔 {interval}日)" if interval is not None else ""))
    print(f"  母数: old={len(old_rows)} / new={len(new_rows)}  突合キー=item_id(in-place) + 仕入元URL(relist)")
    print(f"  露出基準: old={'PL累計' if pl_old else 'organic'} / new={'PL累計' if pl_new else 'organic'}", end="")
    if not comparable:
        print("  ⚠ 基準が違う = バケツ移動は分類ロジック変更による疑い。効果と解釈しない(SALES/価格のみ信頼)")
    else:
        print("  ✓ 同基準")
    if interval is not None and interval <= 2:
        print(f"  ⚠ 間隔 {interval}日 = 短い。eBay impression 蓄積が追いつかず露出系は誤差含み。")
    if old_has_su == 0:
        print("  ⚠ 旧世代に supply_url 無し = relist追跡(取下再出品の前後紐付け)は不可。in-place のみ追える。"
              "\n    → supply_url を焼き込んだ funnel が2世代揃ってから relist 効果が測れる。")
    else:
        print(f"  仕入元URL紐付け: old={old_has_su}件 / new={len(new_by_supply)}件 = relist個体(id変・title変)を追跡可")

    # コホート追跡: 前世代で「直す対象」だった listing が今どうなったか
    cohorts = {b: [] for b in FIX_BUCKETS}
    detail = []   # CSV 用
    for r in old_rows:
        bs = _flags(r) & set(FIX_BUCKETS)
        if not bs:
            continue
        nr, state = match_new(r, new_by_id, new_by_supply)
        if state == "gone":
            vd, gain = "消滅(End/売切)", 0
            for b in bs:
                cohorts[b].append("gone")
        else:
            vd, gain = verdict(r, nr, state, comparable)
            tag = "sold" if vd == "SOLD" else ("relisted" if state == "relisted" else vd)
            for b in bs:
                cohorts[b].append(tag)
        detail.append({
            "コホート": "|".join(sorted(bs)),
            "状態": {"in_place": "在続", "relisted": "取下再出品", "gone": "消滅"}[state],
            "判定": vd,
            "系統": dw.vein_of(r.get("title") or ""),
            "商品名": r.get("title", ""),
            "site": r.get("site", ""),
            "old_露出": round(exposure(r, pl_old), 1),
            "new_露出": round(exposure(nr, pl_new), 1) if nr else "",
            "old_CTR": r.get("ctr_total") or r.get("ctr", ""),
            "new_CTR": (nr.get("ctr_total") or nr.get("ctr", "")) if nr else "",
            "old_sold": int(sold_of(r)),
            "new_sold": int(sold_of(nr)) if nr else "",
            "old_$": f"{_f(r.get('price')):.0f}",
            "new_$": f"{_f(nr.get('price')):.0f}" if nr else "",
            "eBay URL": (nr or r).get("ebay_url", ""),
        })

    # コホート別サマリー
    print("\n--- コホート別: 前世代『直す対象』が今どうなったか ---")
    from collections import Counter
    label = {"sold": "✅売れた", "改善(バケツ脱出)": "改善", "停滞(同バケツ残)": "停滞",
             "悪化/横ばい": "横ばい", "relisted": "取下再出品", "gone": "消滅", "基準差(判定不能)": "基準差"}
    for b in FIX_BUCKETS:
        items = cohorts[b]
        if not items:
            continue
        c = Counter(items)
        parts = [f"{label.get(k, k)}{v}" for k, v in c.most_common()]
        print(f"  {b:<11}({len(items):>3}件): " + " / ".join(parts))

    sold_n = sum(1 for d in detail if d["判定"] == "SOLD")
    print(f"\n  合計: 追跡 {len(detail)}件 中 ✅売れた {sold_n}件")
    if not comparable:
        print("  ※ 基準差ありのため『改善/停滞』は分類変更が混入。次回(同基準どうし)から効果測定が機能する。")

    # 全体メトリクス (基準差があっても sales / 在庫 は信頼できる)
    def total_sold(rows):
        return sum(sold_of(r) for r in rows)
    def n_oos(rows):
        return sum(1 for r in rows if "OUT_OF_STOCK" in _flags(r))
    print("\n--- 全体メトリクス (世代比較) ---")
    print(f"  総販売(sold_qty+90d): {total_sold(old_rows):.0f} → {total_sold(new_rows):.0f}")
    print(f"  在庫切れ件数        : {n_oos(old_rows)} → {n_oos(new_rows)}")
    for b in FIX_BUCKETS + ("RELIST", "RESTOCK", "CULL"):
        o = sum(1 for r in old_rows if b in _flags(r))
        nn = sum(1 for r in new_rows if b in _flags(r))
        print(f"  {b:<11}: {o} → {nn}")

    # CSV 出力 (売れた→改善→停滞→横ばい の順 = 効いた順)
    order = {"SOLD": 0, "改善(バケツ脱出)": 1, "停滞(同バケツ残)": 2, "悪化/横ばい": 3,
             "基準差(判定不能)": 4, "消滅(End/売切)": 5}
    detail.sort(key=lambda d: (order.get(d["判定"], 9), -_f(d["old_$"])))
    stamp = f"{d_old}_to_{d_new}"
    path = os.path.join(DESK, f"効果測定_{stamp}.csv")
    base, ext = os.path.splitext(path)
    f = None
    for i in range(20):
        try:
            f = open(path if i == 0 else f"{base}_{i+1}{ext}", "w", newline="", encoding="utf-8-sig")
            path = f.name
            break
        except PermissionError:
            continue
    if f is None:
        sys.exit("CSV を開けません (既存ファイルがロック中?)。")
    with f:
        w = csv.DictWriter(f, fieldnames=list(detail[0].keys()) if detail else ["(対象なし)"])
        w.writeheader()
        for d in detail:
            w.writerow(d)
    print(f"\nCSV出力: {path}")
    print("▶ 『✅売れた / 改善』が多ければ打ち手は効いている。『停滞』が多い系統=より深い改修(出品くんタイトル生成)へ。")


if __name__ == "__main__":
    main()
