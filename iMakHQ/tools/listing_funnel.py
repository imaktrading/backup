#!/usr/bin/env python3
"""
出品物フルファネル分析 (iMakHQ / 出品くんドメイン) — Seller Hub レポート版

eBay API を一切使わず、Seller Hub から DL する 4 レポートだけでファネルを組む。
(Analytics getTrafficReport の 100/日 クォータ問題を完全回避。bulk は eBay 公式も
 レポート DL を想定している = これが正規ルート)。

データ源 (--data-dir 配下、ファイル名 glob で自動検出):
  1. all-active   : eBay-all-active-listings-report-*.csv  … 全4サイト母集団 (qty/watchers/sold/price/site)
  2. quality      : Listing quality report*.xlsx            … US per-listing 深いファネル
                    (Daily impressions / CTR / Sales conversion / 適正価格 / item specifics 欠落 / 写真数 …)
  3. unsold       : eBay-unsold-listings-report-*.csv        … 売れ残り (Sold status / Relist status)
  4. orders       : *orders-report-*.csv                     … 実売 (Item Number 別に集計)

「今見る」snapshot より上位互換: impressions/CTR/転換率/適正価格 を per-listing で持つ。
これにより「views=0」の症状を「検索に出てない/クリックされない/買われない」の3原因に分解できる。

切り口 (在庫あり=qty!=0 に限定):
  - NO_SEARCH  : impressions ほぼ0 → 検索に出ていない (キーワード/カテゴリ)
  - NO_CLICK   : impr有るが CTR下位 → タイトル/サムネ/価格
  - NO_CONVERT : CTR有るが無販売   → 価格(適正価格比)/説明
  - OVERPRICED : 価格 > eBay trending price → 値付け
  (LQR 非対象=非US等は views/watchers ベースの簡易判定 DEAD_SIMPLE)

使い方:
  python listing_funnel.py                          # 既定 data-dir
  python listing_funnel.py --data-dir "C:/path/to/reports"
"""
import argparse
import csv
import datetime
import glob
import os
import re
import statistics
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

DEFAULT_DATA_DIR = r"C:\dev\iMak_data\seller_hub\reports"
FALLBACK_DATA_DIR = r"C:\Users\imax2\OneDrive\デスクトップ\新しいフォルダー (2)"
OUT_DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "funnel_output"))
DESKTOP = r"C:\Users\imax2\OneDrive\デスクトップ"

# 分類しきい値
TH_IMPR_NONE = 3        # 【fallback: PLレポート無し時】1日あたり organic impr がこれ以下 = 検索に出ていない
TH_IMPR_SHOWN = 8       # 【fallback】これ以上 = 露出あり
# 全件プロモ運用では露出の主成分は PL(広告) impressions。LQR の Daily impr は organic のみで
# PL を見落とす → NO_SEARCH 偽陽性 (実は広告で表示されてるがクリックされてない=NO_CLICK) を生む。
# PLレポート有り時は organic+PL の累計 impr で判定 (累計=CTRを判定できるサンプル数の意味)。
TH_PL_NONE = 30         # organic+PL 累計 impr がこれ以下 = ほぼ表示されてない (=真の NO_SEARCH)
TH_PL_SHOWN = 100       # 累計 impr がこれ以上 = CTR を判定できるサンプル十分
TH_AGE_MIN = 21         # 出品からこれ未満(日) = 新規 → impr低は時間不足なので NO_SEARCH 除外


def start_to_age(start):
    """active CSV の Start date ('Mar-06-25 ...') → 経過日数。不明は 0。"""
    if not start:
        return 0
    m = re.match(r"([A-Za-z]{3}-\d{2}-\d{2})", start.strip())
    if not m:
        return 0
    try:
        d = datetime.datetime.strptime(m.group(1), "%b-%d-%y").date()
        return max((datetime.date.today() - d).days, 0)
    except ValueError:
        return 0


def _f(v):
    try:
        return float(str(v).strip().replace(",", "").replace("$", ""))
    except (ValueError, AttributeError):
        return 0.0


def _i(v):
    try:
        return int(float(str(v).strip().replace(",", "")))
    except (ValueError, AttributeError):
        return 0


def find_file(data_dir, pattern):
    hits = glob.glob(os.path.join(data_dir, pattern))
    return max(hits, key=os.path.getmtime) if hits else None


def _norm_title(t):
    return re.sub(r"\s+", " ", (t or "").lower()).strip()


def build_us_title_map(active):
    """US出品の title→item_id。eBayリンクを常に US版(USD表示)にするための解決表。
    同カードは全サイト同一タイトルで出品されるため title 完全一致で US版に紐付く。"""
    return {_norm_title(a["title"]): iid for iid, a in active.items() if a.get("site") == "US"}


def us_ebay_url(row, us_by_title):
    """row の eBayリンクを US版優先で返す (US出品が無ければ自サイト)。"""
    iid = us_by_title.get(_norm_title(row.get("title", ""))) or row["item_id"]
    return f"https://www.ebay.com/itm/{iid}"


def load_active(path):
    """all-active CSV → {item_id: {...}}。全4サイト母集団。"""
    out = {}
    with open(path, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            iid = (r.get("Item number") or "").strip().strip('"')
            if not iid:
                continue
            out[iid] = {
                "item_id": iid,
                "title": (r.get("Title") or "").strip(),
                "sku": (r.get("Custom label (SKU)") or "").strip(),
                "site": (r.get("Listing site") or "").strip(),
                "qty": _i(r.get("Available quantity")),
                "sold_qty": _i(r.get("Sold quantity")),
                "watch": _i(r.get("Watchers")),
                "price": _f(r.get("Current price") or r.get("Start price")),
                "category": (r.get("eBay category 1 name") or "").strip(),
                "start": (r.get("Start date") or "").strip(),
            }
    return out


def load_quality(path):
    """Listing quality report xlsx の全カテゴリシートを集約 → {item_id: {funnel...}} (US)。"""
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    skip = {"Summary", "Guide", "Google Shopping Rejections"}
    want = {
        "Item Id": "item_id", "Daily impressions per listing": "impr",
        "Click-through rate": "ctr", "Sales conversion rate": "conv",
        "eBay trending price": "trend_price", "Number of photos": "photos",
        "Number of keywords in title": "keywords", "Sales count in last 90 days": "sales90",
        "Quantity available": "qty_q", "Item age in days": "age_days",
    }
    out = {}
    for sn in wb.sheetnames:
        if sn in skip:
            continue
        ws = wb[sn]
        hdr_row, cols = None, {}
        for i, row in enumerate(ws.iter_rows(min_row=1, max_row=60, values_only=True)):
            if any(c == "Item title" for c in row if isinstance(c, str)):
                hdr_row = i + 1
                cols = {(c.strip() if isinstance(c, str) else c): j for j, c in enumerate(row) if c}
                break
        if not hdr_row or "Item Id" not in cols:
            continue
        # 'Sales count in last N days' は日数が可変 → 部分一致で拾う
        sales_col = next((j for k, j in cols.items() if isinstance(k, str) and k.startswith("Sales count")), None)
        for row in ws.iter_rows(min_row=hdr_row + 1, max_row=ws.max_row, values_only=True):
            iid = row[cols["Item Id"]] if cols["Item Id"] < len(row) else None
            if iid is None or not str(iid).strip():
                continue
            iid = str(iid).strip().strip('"')
            def g(key):
                j = cols.get(key)
                return row[j] if j is not None and j < len(row) else None
            out[iid] = {
                "impr": _f(g("Daily impressions per listing")),
                "ctr": _f(g("Click-through rate")),
                "conv_raw": g("Sales conversion rate"),
                "trend_price": _f(g("eBay trending price")),
                "photos": _f(g("Number of photos")),
                "keywords": _f(g("Number of keywords in title")),
                "sales90": _i(row[sales_col]) if sales_col is not None and sales_col < len(row) else 0,
                "category": sn,
            }
    return out


def load_unsold(path):
    """unsold CSV → {item_id: {sold_status, relist_status}}。"""
    out = {}
    if not path:
        return out
    with open(path, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            iid = (r.get("Item number") or "").strip().strip('"')
            if iid:
                out[iid] = {"sold_status": (r.get("Sold status") or "").strip(),
                            "relist_status": (r.get("Relist status") or "").strip()}
    return out


def load_promoted(path):
    """Promoted Listings general listing report → {item_id: (total_impr, total_clicks)}。
    total = PL(via eBay placements) + organic。全件プロモ運用では露出の主成分が PL なので、
    organic のみの LQR Daily impr を補正する。先頭に注記行があるためヘッダ行を探す。"""
    out = {}
    if not path:
        return out
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    hi = next((i for i, r in enumerate(rows) if "Item ID" in [c.strip() for c in r]), None)
    if hi is None:
        return out
    idx = {c.strip(): i for i, c in enumerate(rows[hi])}

    def g(r, c):
        j = idx.get(c)
        return r[j] if j is not None and j < len(r) else ""
    KI = "Promoted Listings Impressions (via eBay Placements)"
    KC = "Total Promoted Listings Clicks"
    for r in rows[hi + 1:]:
        iid = (g(r, "Item ID") or "").strip()
        if not iid:
            continue
        ti = _f(g(r, KI)) + _f(g(r, "Organic Impressions"))
        tc = _f(g(r, KC)) + _f(g(r, "Organic Clicks"))
        out[iid] = (ti, tc)
    return out


def classify(rows):
    """在庫(qty!=0)限定でファネル段階別に分類。LQR データ有り=詳細、無し=簡易。"""
    in_stock = [r for r in rows if r["qty"] != 0]
    oos = [r for r in rows if r["qty"] == 0]

    # 在庫切れも分析: 需要シグナル(過去販売/watch/90d販売)があれば再仕入れ価値、皆無なら出品停止候補
    def _demand(r):
        return r["sold_qty"] + r["watch"] + r.get("sales90", 0)
    restock = [r for r in oos if _demand(r) > 0]
    cull = [r for r in oos if _demand(r) == 0]
    restock.sort(key=lambda x: -_demand(x))

    # 露出/CTR の判定基盤を選ぶ: PLレポート有り → organic+PL 累計 impr/ctr + 累計閾値 (正しい)。
    # 無し → 旧 LQR organic-daily + 旧閾値 (後方互換)。
    use_pl = any(r.get("has_pl") for r in in_stock)
    if use_pl:
        def imp(r): return r.get("impr_total", 0.0)
        def ctr(r): return r.get("ctr_total", 0.0)
        def gate(r): return r.get("has_pl")
        th_none, th_shown = TH_PL_NONE, TH_PL_SHOWN
    else:
        def imp(r): return r["impr"]
        def ctr(r): return r["ctr"]
        def gate(r): return r.get("has_lqr")
        th_none, th_shown = TH_IMPR_NONE, TH_IMPR_SHOWN

    # CTR 下位四分位 (露出十分な listing で算出)
    ctrs = sorted([ctr(r) for r in in_stock if gate(r) and imp(r) >= th_shown])
    ctr_q1 = statistics.quantiles(ctrs, n=4)[0] if len(ctrs) >= 4 else (ctrs[0] if ctrs else 0)

    no_search, no_click, no_convert, overpriced, dead_simple, new_wait = [], [], [], [], [], []
    for r in in_stock:
        sold = r["sold_qty"] + r.get("sales90", 0)
        age = r.get("age_days", 0)
        if gate(r):
            if imp(r) <= th_none:
                # 適正化: 新規出品(時間不足)は誤検出 → NEW_WAIT に隔離 (age不明0は対象に残す)
                (new_wait if 0 < age < TH_AGE_MIN else no_search).append(r)
            elif imp(r) >= th_shown and ctr(r) <= ctr_q1:
                no_click.append(r)
            elif sold == 0 and ctr(r) > ctr_q1:
                no_convert.append(r)
            if r["trend_price"] > 0 and r["price"] > r["trend_price"] * 1.05:
                overpriced.append(r)
        else:
            # 判定基盤なし (非US等): views 系が無いので watch/sold で簡易判定
            if sold == 0 and r["watch"] == 0:
                dead_simple.append(r)
    # 適正化: 各バケツを利益額(価格)優先で並べる → 直す価値の高い順
    for b in (no_search, no_click, no_convert):
        b.sort(key=lambda x: -x["price"])
    overpriced.sort(key=lambda x: -(x["price"] - x["trend_price"]))
    # 取下げ再出品(relist)候補 = NO_SEARCH のうち watcher 無し (= relist で失うものが無い)。
    # watcher 有りは relist すると watcher を失う → タイトル編集など in-place 対応に回す。
    relist = [r for r in no_search if r["watch"] == 0]
    relist.sort(key=lambda x: -x["price"])
    return {"NO_SEARCH": no_search, "NO_CLICK": no_click, "NO_CONVERT": no_convert,
            "OVERPRICED": overpriced, "DEAD_SIMPLE": dead_simple, "NEW_WAIT": new_wait,
            "RELIST": relist, "OUT_OF_STOCK": oos, "RESTOCK": restock, "CULL": cull, "ctr_q1": ctr_q1}


def write_xlsx(path, rows, c, summary_lines):
    """バケツ別シートの Excel を出力 (Summary + 各バケツ + eBayリンク)。"""
    import openpyxl
    from openpyxl.styles import Font
    wb = openpyxl.Workbook()
    # Summary
    ws = wb.active
    ws.title = "Summary"
    ws["A1"] = "出品物フルファネル分析 (Seller Hub レポート版)"
    ws["A1"].font = Font(bold=True, size=13)
    for i, line in enumerate(summary_lines, start=3):
        ws.cell(row=i, column=1, value=line)
    buckets = [
        ("NO_SEARCH", "検索に出ていない (キーワード/カテゴリ)"),
        ("NO_CLICK", "クリックされない (サムネ/タイトル/価格)"),
        ("NO_CONVERT", "買われない (価格/説明)"),
        ("OVERPRICED", "適正価格より高い (値下げ余地)"),
        ("NEW_WAIT", "新規出品でimpr低 (時間不足=様子見・改修対象外)"),
        ("RELIST", "取下げ再出品候補 (在庫あり・検索露出ゼロ・watcher無)"),
        ("RESTOCK", "在庫切れだが需要実証済 (再仕入れ優先)"),
        ("CULL", "在庫切れ&需要皆無 (出品停止候補)"),
        ("DEAD_SIMPLE", "非US等・LQR無 (簡易判定)"),
    ]
    r0 = 3 + len(summary_lines) + 1
    ws.cell(row=r0, column=1, value="バケツ").font = Font(bold=True)
    ws.cell(row=r0, column=2, value="件数").font = Font(bold=True)
    ws.cell(row=r0, column=3, value="意味/アクション").font = Font(bold=True)
    for k, (name, desc) in enumerate(buckets, start=r0 + 1):
        ws.cell(row=k, column=1, value=name)
        ws.cell(row=k, column=2, value=len(c.get(name, [])))
        ws.cell(row=k, column=3, value=desc)
    ws.column_dimensions["A"].width = 16
    ws.column_dimensions["C"].width = 44

    cols = [("item_id", 13), ("title", 46), ("site", 6), ("category", 20), ("price", 8),
            ("trend_price", 10), ("qty", 5), ("sold_qty", 6), ("sales90", 8), ("watch", 7),
            ("impr", 7), ("ctr%", 7), ("photos", 7), ("keywords", 9), ("relist_status", 14), ("ebay_url", 32)]
    def write_sheet(sh_name, items):
        if not items:
            return
        sh = wb.create_sheet(sh_name[:31])
        for j, (h, w) in enumerate(cols, start=1):
            sh.cell(row=1, column=j, value=h).font = Font(bold=True)
            sh.column_dimensions[sh.cell(row=1, column=j).column_letter].width = w
        for i, r in enumerate(items, start=2):
            vals = [r["item_id"], r["title"], r["site"], r.get("category", ""), r["price"],
                    r["trend_price"], r["qty"], r["sold_qty"], r.get("sales90", 0), r["watch"],
                    round(r["impr"], 1), round(r["ctr"] * 100, 2), r.get("photos", 0), r.get("keywords", 0),
                    r.get("relist_status", ""), r.get("ebay_url") or f"https://www.ebay.com/itm/{r['item_id']}"]
            for j, v in enumerate(vals, start=1):
                sh.cell(row=i, column=j, value=v)

    # 在庫あり全件 / 在庫なし全件 (Summary の次に配置 = 一覧の起点)
    if rows:
        write_sheet("在庫あり", sorted([r for r in rows if r["qty"] != 0], key=lambda x: (-x["impr"], -x["watch"])))
        write_sheet("在庫なし", sorted([r for r in rows if r["qty"] == 0], key=lambda x: -(x["sold_qty"] + x["watch"])))
    for name, _ in buckets:
        write_sheet(name, c.get(name, []))
    wb.save(path)


def _sec(title, note, items, limit=20):
    print(f"\n=== {title} ({len(items)}件) ===\n   {note}")
    if not items:
        print("   (該当なし)")
        return
    print(f"   {'item_id':<13}{'site':>4}{'impr/d':>7}{'CTR%':>6}{'sold':>5}{'$':>7}{'trend':>7}  title")
    for r in items[:limit]:
        print(f"   {r['item_id']:<13}{r['site']:>4}{r['impr']:>7.0f}{r['ctr']*100:>6.2f}"
              f"{r['sold_qty']+r.get('sales90',0):>5}{r['price']:>7.0f}{r['trend_price']:>7.0f}  {r['title'][:36]}")
    if len(items) > limit:
        print(f"   ... 他 {len(items) - limit} 件 (CSV 参照)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=None, help="4レポートを置いたフォルダ")
    ap.add_argument("--no-csv", action="store_true")
    args = ap.parse_args()

    data_dir = args.data_dir or (DEFAULT_DATA_DIR if os.path.isdir(DEFAULT_DATA_DIR)
                                 and glob.glob(os.path.join(DEFAULT_DATA_DIR, "*active*")) else FALLBACK_DATA_DIR)
    if not os.path.isdir(data_dir):
        sys.exit(f"data-dir が見つかりません: {data_dir}\n--data-dir で4レポートのフォルダを指定してください。")

    f_active = find_file(data_dir, "*all-active-listings*.csv")
    f_quality = find_file(data_dir, "Listing quality report*.xlsx")
    f_unsold = find_file(data_dir, "*unsold-listings*.csv")
    f_promoted = find_file(data_dir, "*promoted-listing*report*.csv")
    if not f_active:
        sys.exit(f"all-active CSV が {data_dir} に見つかりません。")
    print(f"data-dir: {data_dir}")
    print(f"  active  : {os.path.basename(f_active)}")
    print(f"  quality : {os.path.basename(f_quality) if f_quality else '(なし=簡易判定)'}")
    print(f"  unsold  : {os.path.basename(f_unsold) if f_unsold else '(なし)'}")
    print(f"  promoted: {os.path.basename(f_promoted) if f_promoted else '(なし=organic限定の旧判定)'}")

    active = load_active(f_active)
    quality = load_quality(f_quality) if f_quality else {}
    unsold = load_unsold(f_unsold)
    promoted = load_promoted(f_promoted)
    us_by_title = build_us_title_map(active)  # eBayリンクを常に US版(USD)に解決

    rows = []
    for iid, a in active.items():
        q = quality.get(iid)
        r = dict(a)
        r["ebay_url"] = us_ebay_url(a, us_by_title)
        r["has_lqr"] = bool(q)
        r["impr"] = q["impr"] if q else 0.0          # organic 日次 (LQR・CSV/demand_winners 互換用に温存)
        r["ctr"] = q["ctr"] if q else 0.0
        pl = promoted.get(iid)
        r["has_pl"] = bool(pl)
        r["impr_total"] = pl[0] if pl else 0.0        # organic+PL 累計 (分類の正しい露出指標)
        r["ctr_total"] = (pl[1] / pl[0]) if pl and pl[0] else 0.0
        r["trend_price"] = q["trend_price"] if q else 0.0
        r["sales90"] = q["sales90"] if q else 0
        r["age_days"] = start_to_age(a.get("start", "")) or (q.get("age_days", 0) if q else 0)
        r["photos"] = q["photos"] if q else 0
        r["keywords"] = q["keywords"] if q else 0
        u = unsold.get(iid, {})
        r["relist_status"] = u.get("relist_status", "")
        rows.append(r)

    from collections import Counter
    site_c = Counter(r["site"] for r in rows)
    oos = sum(1 for r in rows if r["qty"] == 0)
    in_stock = [r for r in rows if r["qty"] != 0]
    lqr_n = sum(1 for r in rows if r["has_lqr"])
    n = max(len(rows), 1)
    summary_lines = [
        f"対象レポート: {os.path.basename(f_active)} 他",
        f"listing={len(rows)}  サイト別={dict(site_c)}",
        f"在庫切れqty0={oos}件({oos*100//n}%)  在庫あり={len(in_stock)}件  LQR深掘り対象(US)={lqr_n}件",
    ]
    print(f"\n出品物フルファネル分析 (Seller Hub レポート版・API不使用)")
    for ln in summary_lines[1:]:
        print("   " + ln)

    c = classify(rows)
    _pl_on = any(r.get("has_pl") for r in rows)
    _none, _shown = (TH_PL_NONE, TH_PL_SHOWN) if _pl_on else (TH_IMPR_NONE, TH_IMPR_SHOWN)
    _basis = "organic+PL累計" if _pl_on else "organic日次"
    print(f"   (適正化) 露出基盤={_basis} (PLレポート{'有' if _pl_on else '無'}) / 新規<{TH_AGE_MIN}日は NEW_WAIT 隔離={len(c['NEW_WAIT'])}件 / 各バケツ価格順")
    _sec("① 検索に出ていない NO_SEARCH", f"在庫あり & 出品>={TH_AGE_MIN}日 & 露出({_basis})<={_none} → 真の検索不可。キーワード or 取下げ再出品 (価格高い順)", c["NO_SEARCH"])
    print(f"   └ うち取下げ再出品(relist)候補(watcher無=失うもの無): {len(c['RELIST'])}件 → seller_hub_relist.py で検索リフレッシュ")
    _sec("② クリックされない NO_CLICK", f"在庫あり & 露出({_basis})>={_shown} & CTR下位25%({c['ctr_q1']*100:.2f}%) → タイトル/サムネ/価格", c["NO_CLICK"])
    _sec("③ 買われない NO_CONVERT", "在庫あり & CTR有 & 無販売 → 価格(適正価格比)/説明", c["NO_CONVERT"])
    _sec("④ 高すぎ OVERPRICED", "在庫あり & 価格 > eBay適正価格×1.05 → 値下げ余地 (差額大きい順)", c["OVERPRICED"])

    def _sec_oos(title, note, items, limit=20):
        print(f"\n=== {title} ({len(items)}件) ===\n   {note}")
        if not items:
            print("   (該当なし)"); return
        print(f"   {'item_id':<13}{'site':>4}{'sold':>5}{'watch':>6}{'$':>7}  title")
        for r in items[:limit]:
            print(f"   {r['item_id']:<13}{r['site']:>4}{r['sold_qty']+r.get('sales90',0):>5}{r['watch']:>6}{r['price']:>7.0f}  {r['title'][:38]}")
        if len(items) > limit:
            print(f"   ... 他 {len(items) - limit} 件 (CSV 参照)")

    print("\n--- 在庫切れ(qty0)の分析 ---")
    _sec_oos("⑤ 再仕入れ優先 RESTOCK", "在庫切れ & 過去販売 or watcher 有 → 需要実証済、仕入れ先を再確保 (需要大きい順)", c["RESTOCK"])
    print(f"\n(参考) CULL(在庫切れ&需要皆無=出品停止候補): {len(c['CULL'])}件 — 一度も売れず watcher も付かず。整理対象")
    print(f"(参考) DEAD_SIMPLE(非US等・LQR無): {len(c['DEAD_SIMPLE'])}件")

    if not args.no_csv:
        os.makedirs(OUT_DIR, exist_ok=True)
        path = os.path.join(OUT_DIR, f"funnel_{datetime.date.today():%Y%m%d}.csv")
        for r in rows:
            tags = []
            if r["qty"] == 0: tags.append("OUT_OF_STOCK")
            for k in ("NO_SEARCH", "NO_CLICK", "NO_CONVERT", "OVERPRICED", "DEAD_SIMPLE", "NEW_WAIT", "RELIST", "RESTOCK", "CULL"):
                if r in c[k]: tags.append(k)
            r["flags"] = "|".join(tags)
        fields = ["item_id", "title", "site", "category", "price", "trend_price", "qty", "sold_qty",
                  "sales90", "watch", "impr", "ctr", "impr_total", "ctr_total", "photos", "keywords",
                  "has_lqr", "relist_status", "age_days", "flags", "ebay_url"]
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            for r in sorted(rows, key=lambda x: (-x["impr"], -x["watch"])):
                w.writerow(r)
        print(f"CSV 出力: {path}")

    # 見やすいバケツ別 Excel をデスクトップに出力
    out_dir = DESKTOP if os.path.isdir(DESKTOP) else OUT_DIR
    xlsx_path = os.path.join(out_dir, f"出品ファネル分析_{datetime.date.today():%Y%m%d}.xlsx")
    write_xlsx(xlsx_path, rows, c, summary_lines)
    print(f"Excel 出力: {xlsx_path}")


if __name__ == "__main__":
    main()
