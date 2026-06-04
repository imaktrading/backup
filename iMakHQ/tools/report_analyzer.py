#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""出品物 全観点分析 — Seller Hub 4レポートをあらゆる角度で分析する。

入力 (C:/dev/iMak_data/seller_hub/reports/):
  - eBay-all-active-listings-report-*.csv   (母集団: 全site / qty/watch/sold/price/category/condition/grade/start)
  - eBay-unsold-listings-report-*.csv       (死蔵: Sold status / Relist status)
  - ebay-all-orders-report-*.csv            (実売の真実: 買い手国 / 売価 / 日付 / promoted)
  - Listing quality report*.xlsx            (impr/CTR — 補助。本scriptでは active/orders を主軸)

出力: デスクトップに 出品物_全観点分析_YYYYMMDD.md (人が読む統合レポート)
"""
import csv
import datetime
import glob
import os
import re
import sys
from collections import defaultdict

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

D = r"C:\dev\iMak_data\seller_hub\reports"
DESK = r"C:\Users\imax2\OneDrive\デスクトップ"


def _f(v):
    try:
        return float(str(v).replace(",", "").replace("$", "").strip())
    except (ValueError, TypeError):
        return 0.0


def _latest(pat):
    fs = glob.glob(os.path.join(D, pat))
    return max(fs, key=os.path.getmtime) if fs else None


def load_active():
    p = _latest("eBay-all-active-listings-report-*.csv")
    return p, list(csv.DictReader(open(p, encoding="utf-8-sig", errors="replace")))


def load_unsold():
    p = _latest("eBay-unsold-listings-report-*.csv")
    return list(csv.DictReader(open(p, encoding="utf-8-sig", errors="replace")))


def load_lqr():
    """Listing quality report (xlsx) の Summary を解析。
    カテゴリ別: GMVランク / 総セラー数 / 改善可能listing数 / eBay推奨(●) を抽出。"""
    p = _latest("Listing quality report*.xlsx")
    if not p:
        return None, []
    try:
        import openpyxl
    except ImportError:
        return p, []
    wb = openpyxl.load_workbook(p, read_only=True)
    ws = wb["Summary"]
    cats, cur = [], None
    for row in ws.iter_rows(values_only=True):
        cells = [str(c).strip() for c in row if c is not None and str(c).strip()]
        if not cells:
            continue
        line = " | ".join(cells)
        if "rank by sales (GMV)" in line:
            name = cells[0].split("/")[0].strip()
            rank = re.search(r"value:\s*([\d,]+)\s*out of\s*([\d,]+)", line)
            cond = re.search(r"condition:\s*(\w+)", line)
            impr = re.search(r"(\d+)\s*listings can be improved", line)
            cur = {"cat": name, "cond": cond.group(1) if cond else "",
                   "rank": int(rank.group(1).replace(",", "")) if rank else 0,
                   "total": int(rank.group(2).replace(",", "")) if rank else 0,
                   "improvable": int(impr.group(1)) if impr else 0, "recs": []}
            cats.append(cur)
        elif cur is not None:
            for c in cells:
                if c.startswith("●"):
                    cur["recs"].append(c.lstrip("● ").strip())
    return p, cats


def load_orders():
    """orders は row0空 / row1ヘッダ / row2+ データ の特殊形式。
    去年+今年など複数ファイルを全部結合し、Order Number で重複除去。"""
    files = sorted(glob.glob(os.path.join(D, "*orders*.csv")))
    out, seen = [], set()
    for p in files:
        rows = list(csv.reader(open(p, encoding="utf-8-sig", errors="replace")))
        if len(rows) < 2:
            continue
        hdr = rows[1]
        for r in rows[2:]:
            if len(r) < 30 or not r[0].strip():
                continue
            rec = {hdr[j]: (r[j] if j < len(r) else "") for j in range(len(hdr))}
            on = (rec.get("Order Number") or "").strip()
            if on and on in seen:
                continue
            if on:
                seen.add(on)
            out.append(rec)
    return out


def category_of(title, ebay_cat):
    """eBay公式カテゴリ優先、無ければ title から franchise 推定。"""
    if ebay_cat:
        return ebay_cat
    return "(no category)"


def franchise_of(title):
    t = (title or "").lower()
    if "g-shock" in t or "casio" in t:
        return "G-SHOCK"
    if "uniqlo" in t or " ut " in t or t.startswith("ut ") or "t-shirt" in t or "airism" in t or "pufftech" in t:
        return "UNIQLO/UT"
    if any(k in t for k in ("sanrio", "kuromi", "hello kitty", "cinnamoroll", "pochacco", "my melody")):
        return "Sanrio"
    if "psa 10" in t or "psa10" in t:
        return "PSA card"
    if "porter" in t or "tanker" in t:
        return "PORTER"
    if "montbell" in t:
        return "Montbell"
    if "ichiban" in t:
        return "Ichiban Kuji"
    if "figuarts" in t or "figure" in t or "figurizma" in t:
        return "Figure"
    if "reel" in t or "shimano" in t or "daiwa" in t:
        return "Reel"
    return "other"


def bar(n, mx, width=24):
    return "█" * int(round(n / mx * width)) if mx else ""


def main():
    pa, active = load_active()
    unsold = load_unsold()
    orders = load_orders()
    today = datetime.date.today().strftime("%Y%m%d")
    L = []
    def w(s=""): L.append(s)

    w(f"# 出品物 全観点分析  ({today})")
    w(f"_source: {os.path.basename(pa)} ほか Seller Hub 4レポート_\n")

    # ---------- 0. 母集団 ----------
    sites = defaultdict(int)
    instock = 0
    prod = defaultdict(lambda: {"sold": 0.0, "watch": 0.0, "qty": 0.0, "price": 0.0,
                                "title": "", "cat": "", "fr": "", "sites": set(), "grade": "", "cond": ""})
    for r in active:
        sites[r.get("Listing site", "?")] += 1
        q = _f(r.get("Available quantity"))
        if q > 0:
            instock += 1
        k = (r.get("Title") or "").strip().lower()
        p = prod[k]
        p["sold"] += _f(r.get("Sold quantity"))
        p["watch"] += _f(r.get("Watchers"))
        p["qty"] = max(p["qty"], q)
        p["price"] = _f(r.get("Current price")) or p["price"]
        p["title"] = r.get("Title") or p["title"]
        p["cat"] = r.get("eBay category 1 name") or p["cat"]
        p["fr"] = franchise_of(r.get("Title"))
        p["sites"].add(r.get("Listing site", "?"))
        p["grade"] = r.get("CD:Grade - (ID: 27502)") or p["grade"]
        p["cond"] = r.get("Condition") or p["cond"]
    nprod = len(prod)
    w("## 0. 母集団")
    w(f"- active 行(全site×item): **{len(active):,}**  →  商品(title重複除去): **{nprod:,}**  (＝同一商品が平均 {len(active)/max(nprod,1):.1f} サイトに出品)")
    w(f"- 在庫あり(qty>0)行: {instock:,}  /  在庫切れ行: {len(active)-instock:,}")
    w(f"- サイト別 listing: " + " / ".join(f"{k}:{v}" for k, v in sorted(sites.items(), key=lambda x: -x[1])))
    w("")

    # ---------- 1. 実売の真実 (orders) ----------
    w("## 1. 実売の真実 (orders report = 実際に売れた取引)")
    rev = 0.0
    bycountry = defaultdict(lambda: {"n": 0, "rev": 0.0})
    byfr = defaultdict(lambda: {"n": 0, "rev": 0.0})
    promoted = 0
    dates = []
    items = []
    for o in orders:
        sf = _f(o.get("Sold For"))
        qty = _f(o.get("Quantity")) or 1
        rev += sf
        c = (o.get("Buyer Country") or o.get("Ship To Country") or "?").strip()
        bycountry[c]["n"] += 1; bycountry[c]["rev"] += sf
        fr = franchise_of(o.get("Item Title"))
        byfr[fr]["n"] += 1; byfr[fr]["rev"] += sf
        if (o.get("Sold Via Promoted Listings") or "").strip().lower() in ("yes", "true", "1"):
            promoted += 1
        sd = (o.get("Sale Date") or "").strip()
        if sd:
            dates.append(sd)
        items.append((o.get("Item Title", "")[:55], sf, c, fr))
    w(f"- 取引数: **{len(orders)}件**  /  売上(Sold For 合計): **${rev:,.0f}**  /  平均単価: ${rev/max(len(orders),1):,.0f}")
    if dates:
        w(f"- 期間: {min(dates)} 〜 {max(dates)}")
    w(f"- Promoted Listings 経由: {promoted}/{len(orders)} 件 ({promoted/max(len(orders),1)*100:.0f}%)")
    w("\n**買い手の国 (=実需の地理)**\n")
    w("| 国 | 件数 | 売上 |")
    w("|---|---:|---:|")
    mx = max((d["n"] for d in bycountry.values()), default=1)
    for c, d in sorted(bycountry.items(), key=lambda x: -x[1]["n"]):
        w(f"| {c} | {d['n']} | ${d['rev']:,.0f} |")
    w("\n**実売 franchise別**\n")
    w("| franchise | 件数 | 売上 | 平均単価 |")
    w("|---|---:|---:|---:|")
    for fr, d in sorted(byfr.items(), key=lambda x: -x[1]["rev"]):
        w(f"| {fr} | {d['n']} | ${d['rev']:,.0f} | ${d['rev']/max(d['n'],1):,.0f} |")
    w("\n**実際に売れた商品 (全件)**\n")
    for t, sf, c, fr in sorted(items, key=lambda x: -x[1]):
        w(f"- ${sf:,.0f} [{c}] {t}")
    w("")

    # ---------- 2. franchise別 カバー vs 需要 (active, 商品単位) ----------
    w("## 2. franchise別 カバー vs 需要 (商品単位・重複除去)")
    g = defaultdict(lambda: {"prod": 0, "instock": 0, "sold": 0.0, "watch": 0.0, "soldprod": 0})
    for p in prod.values():
        d = g[p["fr"]]
        d["prod"] += 1
        if p["qty"] > 0:
            d["instock"] += 1
        d["sold"] += p["sold"]; d["watch"] += p["watch"]
        if p["sold"] > 0:
            d["soldprod"] += 1
    w("| franchise | 商品数 | 在庫あり | 実売数 | 売れた商品 | watch計 |")
    w("|---|---:|---:|---:|---:|---:|")
    for fr, d in sorted(g.items(), key=lambda x: -x[1]["watch"]):
        w(f"| {fr} | {d['prod']} | {d['instock']} | {int(d['sold'])} | {d['soldprod']} | {int(d['watch'])} |")
    w("")

    # ---------- 3. eBay公式カテゴリ別 ----------
    w("## 3. eBay公式カテゴリ別 (active category 1 name)")
    cat = defaultdict(lambda: {"n": 0, "watch": 0.0, "sold": 0.0})
    for r in active:
        c = r.get("eBay category 1 name") or "(none)"
        cat[c]["n"] += 1; cat[c]["watch"] += _f(r.get("Watchers")); cat[c]["sold"] += _f(r.get("Sold quantity"))
    w("| カテゴリ | listing | watch | sold |")
    w("|---|---:|---:|---:|")
    for c, d in sorted(cat.items(), key=lambda x: -x[1]["n"])[:15]:
        w(f"| {c} | {d['n']} | {int(d['watch'])} | {int(d['sold'])} |")
    w("")

    # ---------- 4. サイト別 needs (watch/sold が乗るサイト) ----------
    w("## 4. サイト別 需要 (どのサイトが watch/sold を生むか)")
    st = defaultdict(lambda: {"n": 0, "watch": 0.0, "sold": 0.0})
    for r in active:
        s = r.get("Listing site", "?")
        st[s]["n"] += 1; st[s]["watch"] += _f(r.get("Watchers")); st[s]["sold"] += _f(r.get("Sold quantity"))
    w("| site | listing | watch | sold | watch/100listing |")
    w("|---|---:|---:|---:|---:|")
    for s, d in sorted(st.items(), key=lambda x: -x[1]["watch"]):
        w(f"| {s} | {d['n']} | {int(d['watch'])} | {int(d['sold'])} | {d['watch']/max(d['n'],1)*100:.1f} |")
    w("")

    # ---------- 5. 価格帯別 ----------
    w("## 5. 価格帯別 (商品単位・在庫あり)")
    bands = [(0, 30), (30, 50), (50, 100), (100, 200), (200, 300), (300, 400), (400, 600), (600, 9999)]
    pb = {b: {"n": 0, "watch": 0.0, "sold": 0.0} for b in bands}
    for p in prod.values():
        if p["qty"] <= 0:
            continue
        for b in bands:
            if b[0] <= p["price"] < b[1]:
                pb[b]["n"] += 1; pb[b]["watch"] += p["watch"]; pb[b]["sold"] += p["sold"]
                break
    w("| 価格帯 | 商品数 | watch | 実売 |")
    w("|---|---:|---:|---:|")
    for b in bands:
        d = pb[b]
        w(f"| ${b[0]}-{b[1]} | {d['n']} | {int(d['watch'])} | {int(d['sold'])} |")
    w("")

    # ---------- 6. 出品年齢別 ----------
    w("## 6. 出品からの経過 (Start date)")
    def age(s):
        m = re.match(r"([A-Za-z]{3}-\d{2}-\d{2})", (s or "").strip())
        if not m:
            return None
        try:
            d = datetime.datetime.strptime(m.group(1), "%b-%d-%y").date()
            return (datetime.date.today() - d).days
        except ValueError:
            return None
    agebuckets = defaultdict(lambda: {"n": 0, "sold": 0.0, "watch": 0.0})
    for r in active:
        a = age(r.get("Start date"))
        if a is None:
            key = "不明"
        elif a < 21:
            key = "0-21日(新規)"
        elif a < 60:
            key = "21-60日"
        elif a < 120:
            key = "60-120日"
        else:
            key = "120日+"
        d = agebuckets[key]
        d["n"] += 1; d["sold"] += _f(r.get("Sold quantity")); d["watch"] += _f(r.get("Watchers"))
    w("| 経過 | listing | sold | watch |")
    w("|---|---:|---:|---:|")
    for k in ["0-21日(新規)", "21-60日", "60-120日", "120日+", "不明"]:
        if k in agebuckets:
            d = agebuckets[k]
            w(f"| {k} | {d['n']} | {int(d['sold'])} | {int(d['watch'])} |")
    w("")

    # ---------- 7. 死蔵 (unsold report) ----------
    w("## 7. 死蔵・再出品 (unsold report)")
    ss = defaultdict(int); rs = defaultdict(int)
    for r in unsold:
        ss[(r.get("Sold status") or "?").strip()] += 1
        rs[(r.get("Relist status") or "?").strip()] += 1
    w(f"- unsold report 行数: {len(unsold):,}")
    w("- Sold status: " + " / ".join(f"{k}:{v}" for k, v in sorted(ss.items(), key=lambda x: -x[1]) if k))
    w("- Relist status: " + " / ".join(f"{k}:{v}" for k, v in sorted(rs.items(), key=lambda x: -x[1]) if k))
    w("")

    # ---------- 8. 潜在需要 (watch高・未売) ----------
    w("## 8. 潜在需要 (watch 高いが SOLD 0 = 取りこぼし)")
    latent = sorted([p for p in prod.values() if p["sold"] == 0 and p["watch"] > 0], key=lambda p: -p["watch"])
    w(f"- 該当商品: {len(latent)} (実売した商品 {sum(1 for p in prod.values() if p['sold']>0)} の何倍も厚い)")
    w("\n| watch | 価格 | franchise | 商品 |")
    w("|---:|---:|---|---|")
    for p in latent[:20]:
        w(f"| {int(p['watch'])} | ${p['price']:.0f} | {p['fr']} | {p['title'][:50]} |")
    w("")

    # ---------- 9. 総合需要スコア ----------
    w("## 9. 総合需要スコア上位 (SOLD*100 + WATCH*8、商品単位)")
    def dem(p):
        return p["sold"] * 100 + p["watch"] * 8
    top = sorted(prod.values(), key=lambda p: -dem(p))[:25]
    w("\n| スコア | 売 | watch | 価格 | 商品 |")
    w("|---:|---:|---:|---:|---|")
    for p in top:
        w(f"| {dem(p):.0f} | {int(p['sold'])} | {int(p['watch'])} | ${p['price']:.0f} | {p['title'][:48]} |")
    w("")

    # ---------- 10. eBay公式 listing quality 診断 (LQR) ----------
    plq, lqr = load_lqr()
    w("## 10. eBay公式 listing quality 診断 (LQR = 5番目のレポート)")
    if lqr:
        w(f"_source: {os.path.basename(plq)}_\n")
        w("**カテゴリ別 GMVランク / 改善余地**\n")
        w("| カテゴリ | 状態 | GMVランク | 上位% | 改善可能 |")
        w("|---|---|---|---:|---:|")
        for c in lqr:
            pct = f"{c['rank']/c['total']*100:.1f}%" if c["total"] else "?"
            w(f"| {c['cat']} | {c['cond']} | {c['rank']:,}/{c['total']:,} | {pct} | {c['improvable']} |")
        # 推奨の頻度集計 (systemic な弱点)
        reccount = defaultdict(int)
        for c in lqr:
            for r in c["recs"]:
                key = re.sub(r"\d[\d,]*", "N", r)[:60]
                reccount[key] += 1
        w("\n**eBay 推奨の頻度（＝横断的な弱点）**\n")
        for r, n in sorted(reccount.items(), key=lambda x: -x[1]):
            w(f"- ({n}カテゴリ) {r}")
        w("\n**カテゴリ別 推奨詳細**\n")
        for c in lqr:
            if c["recs"]:
                w(f"- **{c['cat']}**: " + " / ".join(c["recs"]))
    else:
        w("(LQR 読込不可 — openpyxl 未導入 or ファイル無し)")
    w("")

    out = os.path.join(DESK, f"出品物_全観点分析_{today}.md")
    open(out, "w", encoding="utf-8").write("\n".join(L))
    # コンソールにも要点
    print("\n".join(L[:60]))
    print(f"\n... (全文は {out})")
    print(f"\n書き出し: {out}")


if __name__ == "__main__":
    main()
