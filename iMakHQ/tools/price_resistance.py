#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""NO_CONVERT 価格抵抗ワークシート — 「クリックは来るが買われない」の最大塊を、
自分の実売価格(proven)と突き合わせて「割高で止まってる」候補を出す。

設計 (2026-06-05 発見):
  NO_CONVERT(CTR有・無販売) は title/写真でなく価格/条件の問題。だが trend_price(eBay
  適正)は大半欠損。代わりに **自分の orders 実売を市場リファレンス**にすると、高クリック
  無販売の 83% が自分の vein 実売中央超え・38% が実売最高すら超え=価格抵抗と判明。
  G-SHOCK は型番系統で精密照合(同系統実売の最高超えが 8/8)。

  drop-ship 留意: 価格=仕入原価+マージン。割高でも「下げられる(原価安)→値下げ」か
  「下げられない(原価高)→撤退寄り」かは Mercari 原価次第 → 各行に原価チェックURLを付ける。
  結論は人が判断 (自動値下げはしない)。

入力: ../funnel_output/funnel_*.csv (NO_CONVERT + impr_total/ctr_total) + orders (実売)
出力: デスクトップ 価格抵抗_YYYYMMDD.csv (乖離大きい順)
"""
import csv
import datetime
import glob
import importlib.util
import os
import statistics
import sys
from collections import defaultdict

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

_HERE = os.path.dirname(os.path.abspath(__file__))
FUNNEL_DIR = os.path.normpath(os.path.join(_HERE, "..", "funnel_output"))
DESK = r"C:\Users\imax2\OneDrive\デスクトップ"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(_HERE, name + ".py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


dw = _load("demand_winners")
rw = _load("restock_worklist")  # mercari_kw 再利用


def _f(v):
    try:
        return float(str(v).replace(",", "").replace("$", "").strip())
    except (ValueError, TypeError):
        return 0.0


def build_proven():
    """orders から vein別・G-SHOCK系統別の実売価格リファレンスを作る。"""
    vein_sold, series_sold = defaultdict(list), defaultdict(list)
    for o in dw.load_orders():
        t = o.get("Item Title", "")
        sp = _f(o.get("Sold For"))
        if not t.strip() or sp <= 0:
            continue
        v = dw.vein_of(t)
        vein_sold[v].append(sp)
        if v == "G-SHOCK":
            s = dw.series_of(t)
            if s:
                series_sold[s].append(sp)
    return vein_sold, series_sold


def proven_ref(vein, title, vein_sold, series_sold):
    """(基準種別, 中央値, 最高値) を返す。系統一致(精密)→vein→なし の順。"""
    if vein == "G-SHOCK":
        s = dw.series_of(title)
        if s and series_sold.get(s):
            ps = series_sold[s]
            return ("系統", statistics.median(ps), max(ps))
    ps = vein_sold.get(vein, [])
    if len(ps) >= 2:
        return ("vein", statistics.median(ps), max(ps))
    return ("なし", None, None)


def clicks_of(r):
    """funnel CSV から総クリック数を復元 (clicks = ctr_total × impr_total)。"""
    return _f(r.get("ctr_total")) * _f(r.get("impr_total"))


def load_targets():
    fs = glob.glob(os.path.join(FUNNEL_DIR, "funnel_*.csv"))
    if not fs:
        sys.exit("funnel_*.csv がありません。先に『📊 ファネル分析』を実行してください。")
    rows = list(csv.DictReader(open(max(fs, key=os.path.getmtime), encoding="utf-8")))
    return [r for r in rows if "NO_CONVERT" in (r.get("flags") or "").split("|")]


def main():
    vein_sold, series_sold = build_proven()
    targets = load_targets()

    recs = []
    for r in targets:
        title = r.get("title", "")
        vein = dw.vein_of(title)
        price = _f(r.get("price"))
        kind, med, mx = proven_ref(vein, title, vein_sold, series_sold)
        ratio = (price / mx) if mx else 0.0          # asking / 実売最高 (>1=実績超え)
        recs.append({"vein": vein, "title": title, "price": price, "kind": kind,
                     "med": med, "mx": mx, "ratio": ratio,
                     "clicks": int(round(clicks_of(r))), "watch": int(_f(r.get("watch"))),
                     "kw": rw.mercari_kw(vein, title), "ebay": r.get("ebay_url", "")})
    # 優先順位: 実績比較可(割高ほど上=乖離大) → 実績なし、同条件はクリック多い(=関心大)順
    recs.sort(key=lambda d: (1 if d["kind"] == "なし" else 0, -(d["ratio"] or 0), -d["clicks"]))

    # スプシ「価格抵抗」タブに集約 (デスクトップCSV廃止 2026-06-07)
    out_rows = [["判断(値下/撤退/様子見)", "系統", "商品名", "現価格", "実売中央", "実売最高",
                 "倍率(現/最高)", "実績基準", "クリック", "watch", "メルカリ原価URL", "eBay URL"]]
    for d in recs:
        out_rows.append(["", d["vein"], d["title"], f"${d['price']:.0f}",
                         f"${d['med']:.0f}" if d["med"] else "-", f"${d['mx']:.0f}" if d["mx"] else "-",
                         f"{d['ratio']:.2f}" if d["ratio"] else "-", d["kind"],
                         d["clicks"], d["watch"], dw.mercari_url(d["kw"]), d["ebay"]])
    try:
        from sheet_io import write_rows_to_tab, MAINT_URL
        write_rows_to_tab("価格抵抗", out_rows)
        print(f"💲 「価格抵抗」タブ更新: {len(out_rows)-1}件 → {MAINT_URL}")
    except Exception as _e:
        print(f"⚠ 「価格抵抗」タブ更新失敗: {type(_e).__name__}: {_e}")

    over = [d for d in recs if d["ratio"] and d["ratio"] > 1]
    none = [d for d in recs if d["kind"] == "なし"]
    print(f"NO_CONVERT (CTR有・無販売) = {len(recs)}件 (全件・優先順位順)")
    print(f"  ① 自分の実売最高を超える価格(倍率>1)=割高で価格抵抗 = {len(over)}件 → 原価見て値下で寄せる候補")
    print(f"  ② 過去一度も売れてない系統/vein(実績なし) = {len(none)}件 → 原価高なら撤退寄り/プレミアムは様子見")
    print(f"  ③ 実績内に収まる(倍率<=1) = {len(recs)-len(over)-len(none)}件 → 価格以外(条件/需要)を疑う")
    print("\n  ▼ 割高 top (現価格 vs 自分の実売最高):")
    for d in over[:10]:
        print(f"    ${d['price']:>4.0f} vs 最高${d['mx']:>4.0f} (x{d['ratio']:.1f}) [{d['kind']}] {d['title'][:40]}")
    # 出力はスプシ「価格抵抗」タブ (上で更新済)
    print("▶ 各行のメルカリ原価URLで仕入値を確認 → 実売価格まで下げられるなら値下、原価高なら撤退寄り。")
    print("※ 自動値下げはしない。drop-ship は価格=原価+マージンなので原価を見て人が判断。")


if __name__ == "__main__":
    main()
