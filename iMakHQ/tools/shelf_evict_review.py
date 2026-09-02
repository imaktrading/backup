#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""棚の閾値を見直す — カテゴリ別に「その年齢まで残った出品が、この先90日で売れる割合」を出す。

なぜ要るか (2026-09-02):
    shelf_evict の STALE_MAX_AGE (TCG 30日 / G-shock 365日) は実測から決めた値だが、
    仕入れ先も相場も動くので **固定してはいけない**。四半期ごとにこれを走らせて、
    数字が変わっていたら閾値を直す。

なぜこの測り方か:
    販売は月8〜12件しかないので、売れた分だけを見ると母数が足りない (実測63件)。
    **まだ売れていない在庫も母数に入れる**と 5,800件規模になり、
    年齢別の売却率が信頼区間つきで出せる。

使い方:
    python shelf_evict_review.py
"""
import collections
import csv
import datetime
import glob
import io
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

REPORTS = r"C:/dev/iMak_data/seller_hub/reports"
FUNNELS = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                        "..", "funnel_output"))
LEDGER_ID = "1MufEUweIJcLv-NwT3KZsEJ_k_yl1rKryaqBZjUH7c2U"
LEDGER_GID = 1814510799
MON = {m: i + 1 for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])}
NORM = {"Armbanduhren": "Wristwatches", "TCG Einzelkarten": "CCG Individual Cards"}
JP = {"CCG Individual Cards": "TCG", "Wristwatches": "G-shock", "T-Shirts": "Tシャツ",
      "Figures & Statues": "フィギュア", "Coats, Jackets & Vests": "モンベル/上着",
      "Bags": "バッグ"}
BANDS = (0, 15, 30, 45, 60, 90, 120, 180, 270, 365)
HORIZON = 90
MIN_DEN = 20
QUOTE = chr(39)


def parse_date(s):
    """'Sep 01, 2026' / 'Aug-30-26' / '2026/09/01' を日付に (純関数)。"""
    s = (s or "").strip()
    if not s:
        return None
    try:
        a = s.replace(",", "").split()
        return datetime.date(int(a[2]), MON[a[0][:3]], int(a[1]))
    except Exception:
        pass
    try:
        a = s.split("-")
        return datetime.date(2000 + int(a[2][:2]), MON[a[0][:3]], int(a[1]))
    except Exception:
        pass
    try:
        a = s.split("/")
        return datetime.date(int(a[0]), int(a[1]), int(a[2]))
    except Exception:
        return None


def wilson(k, n):
    """二項の95%信頼区間 (純関数)。件数が少ない時に断定しないため。"""
    if not n:
        return (0.0, 0.0)
    z = 1.96
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    e = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - e) * 100, min(1.0, c + e) * 100)


def conditional_rate(rows, age, horizon=HORIZON):
    """(経過日数, 売れたか) → その年齢まで残った分が先 horizon 日で売れた (件数, 分母)。

    分母は「その年齢まで残り」かつ「horizon 日先まで観測できている」もの。
    観測期間が来ていない分を分母に入れると売却率を不当に下げる (純関数)。
    """
    at_risk = [(d, e) for d, e in rows if d >= age]
    k = sum(1 for d, e in at_risk if e and d < age + horizon)
    n = sum(1 for d, e in at_risk if e or d >= age + horizon)
    return k, n


def load_start_dates():
    """itemID → 出品開始日 (現在出品レポート + 広告レポート)。"""
    start = {}
    for pat, id_col, date_col in (
            ("eBay-all-active-listings-report-*.csv", "Item number", "Start date"),
            ("*promoted*.csv", "Item ID", "Listing start date")):
        for path in glob.glob(os.path.join(REPORTS, "*", pat)):
            try:
                rows = list(csv.reader(io.open(path, encoding="utf-8-sig", errors="replace")))
            except OSError:
                continue
            hdr = next((i for i, r in enumerate(rows[:8])
                        if any((c or "").strip() == id_col for c in r)), None)
            if hdr is None:
                continue
            h = [(c or "").strip() for c in rows[hdr]]
            if date_col not in h:
                continue
            ii, si = h.index(id_col), h.index(date_col)
            for r in rows[hdr + 1:]:
                if len(r) <= max(ii, si):
                    continue
                iid = (r[ii] or "").strip().lstrip(QUOTE)
                d = parse_date(r[si])
                if iid and d:
                    start.setdefault(iid, d)
    return start


def load_categories():
    """itemID → カテゴリ (ファネルの履歴から)。"""
    cat = {}
    for p in sorted(glob.glob(os.path.join(FUNNELS, "funnel_*.csv"))):
        try:
            for r in csv.DictReader(io.open(p, encoding="utf-8")):
                c = (r.get("category") or "").strip()
                if c:
                    cat[r["item_id"]] = NORM.get(c, c)
        except OSError:
            continue
    return cat


def load_sales():
    """itemID → 最初に売れた日 (販売実績台帳 + eBay注文レポート)。"""
    sale = {}
    try:
        import gspread
        from google.oauth2.service_account import Credentials
        from relist_writeback import CREDS_PATH
        cr = Credentials.from_service_account_file(
            CREDS_PATH, scopes=["https://www.googleapis.com/auth/spreadsheets"])
        v = gspread.authorize(cr).open_by_key(LEDGER_ID).get_worksheet_by_id(
            LEDGER_GID).get_all_values()
        for r in v[1:]:
            iid = (r[1] if len(r) > 1 else "").strip()
            d = parse_date(r[4] if len(r) > 4 else "")
            if iid and d:
                sale[iid] = min(sale.get(iid, datetime.date(2099, 1, 1)), d)
    except Exception as e:                                       # noqa: BLE001
        print("  ⚠ 販売実績台帳を読めません (%s) → 注文レポートだけで続けます" % type(e).__name__)
    for path in glob.glob(os.path.join(REPORTS, "*", "ebay-all-orders-report-*.csv")):
        rows = list(csv.reader(io.open(path, encoding="utf-8-sig", errors="replace")))
        hdr = next((i for i, r in enumerate(rows[:5]) if "Sales Record Number" in r), None)
        if hdr is None:
            continue
        h = rows[hdr]
        ii = h.index("Item Number") if "Item Number" in h else None
        di = h.index("Sale Date") if "Sale Date" in h else None
        for r in rows[hdr + 1:]:
            if ii is None or len(r) <= ii:
                continue
            iid = (r[ii] or "").strip()
            d = parse_date(r[di] if di is not None and di < len(r) else "")
            if iid and d:
                sale[iid] = min(sale.get(iid, datetime.date(2099, 1, 1)), d)
    return sale


def build(today=None):
    """カテゴリ → [(経過日数, 売れたか)]。"""
    today = today or datetime.date.today()
    start, cat, sale = load_start_dates(), load_categories(), load_sales()
    rec = collections.defaultdict(list)
    for iid, st in start.items():
        c = JP.get(cat.get(iid, ""))
        if not c:
            continue
        sd = sale.get(iid)
        if sd and sd >= st:
            rec[c].append(((sd - st).days, 1))
        else:
            rec[c].append(((today - st).days, 0))
    return rec


def main():
    rec = build()
    try:
        import shelf_evict as SE
        cur = dict(SE.STALE_MAX_AGE)
    except Exception:                                            # noqa: BLE001
        cur = {}
    print("# 棚の閾値 見直し (%s)" % datetime.date.today())
    print()
    print("「その年齢まで売れずに残った出品が、この先90日で売れた割合」")
    print("分母%d件未満は載せない (区間が広すぎて判断できないため)" % MIN_DEN)
    print()
    for c, v in sorted(rec.items(), key=lambda x: -len(x[1])):
        if len(v) < 50:
            continue
        line = "## %s  (対象 %d件 / うち販売 %d件)" % (c, len(v), sum(e for _d, e in v))
        if c in cur:
            line += "   ← 今の線: %d日超でEND" % cur[c]
        print(line)
        print("| 年齢 | 分母 | 売れた | 売却率 | 95%区間 |")
        print("|---|---|---|---|---|")
        for a in BANDS:
            k, n = conditional_rate(v, a)
            if n < MIN_DEN:
                continue
            lo, hi = wilson(k, n)
            print("| %d日〜 | %d | %d | %.2f%% | %.2f〜%.2f%% |" % (a, n, k, 100 * k / n, lo, hi))
        print()
    print("※ 数字が今の線と食い違っていたら shelf_evict.STALE_MAX_AGE を直す")
    print("※ 線を動かす前に、この表を daily_report に残すこと (次回との比較用)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
