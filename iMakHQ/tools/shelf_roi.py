#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""棚 (eBay 出品リミット $1M) の配分と、実際に稼いだ利益を突き合わせる (2026-08-26)。

なぜ必要か:
    eBay の出品リミットは **金額**で決まる ($1M)。件数は半分以上あまっているので、
    実質「$1M の陳列ケース」を何に使うかがそのまま売上を決める。
    出品中の watcher や表示回数だけを見ると、**売れて消えた分が入らない**ため
    よく売れるカテゴリほど低く出る (2026-08-26 に実際に誤った: PSA を「効率が悪い」と判定した)。
    正しい材料は「販売実績」スプシ = 売れた分の記録。

出すもの:
    カテゴリごとに 棚をいくら使い / 実際にいくら稼いだか / 棚 $1,000 あたりの利益。
    それを基準に「どのカテゴリの棚を増やす/減らす」の目安を出す。

    ★ミラー (UK/AU/CA) の棚も **親 (US) のカテゴリ**に足す。1商品を出すと mag が
      勝手に3件作るので、その分も含めてはじめて「その商品が使った棚」になる。

使い方:
    python shelf_roi.py            # 直近90日
    python shelf_roi.py --days 180
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cull_end as CE          # noqa: E402
import listing_funnel as LF    # noqa: E402

SALES_SHEET_ID = "1MufEUweIJcLv-NwT3KZsEJ_k_yl1rKryaqBZjUH7c2U"
SALES_GID = 1814510799
SALES_COL = {"item": 1, "date": 4, "country": 5, "price": 6, "profit": 15, "cat": 17}
REPORT_GLOB = r"C:\dev\iMak_data\seller_hub\reports\**\eBay-all-active-listings-report-*.csv"

# 販売実績シートのカテゴリ名 → 商品管理シートのカテゴリ名。
# 表記が違うだけで同じもの。片方にしか無い名前はそのまま使う。
CAT_ALIAS = {
    "バッグ（ポーター）": "バッグ", "バッグ（アネロ）": "バッグ",
    "ユニクロ": "Tシャツ",          # ユニクロUT は管理シートでは Tシャツ
    "ガシャポン": "カプセルトイ",
    "サンリオぬいぐるみ": "その他", "サンリオ文具": "その他", "ダイソー": "その他",
    "ヴィンテージおもちゃ": "その他", "POPMart": "その他",
}


def money(x):
    """'$1,234.56' / '¥1,500' / '-$4.06' → float (純関数, test可)。"""
    s = (x or "").replace("$", "").replace("¥", "").replace(",", "").strip()
    neg = s.startswith("-")
    s = s.lstrip("-").lstrip("+")
    try:
        return (-1.0 if neg else 1.0) * float(s or 0)
    except ValueError:
        return 0.0


def norm_cat(name):
    """カテゴリ名を1つの語彙に寄せる (純関数, test可)。"""
    c = (name or "").strip()
    return CAT_ALIAS.get(c, c) or "(未分類)"


def parse_date(s):
    for fmt in ("%Y/%m/%d", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime((s or "").strip(), fmt).date()
        except ValueError:
            continue
    return None


def sales_by_category(rows2d, since):
    """販売実績シート → {カテゴリ: {件数, 売上$, 利益¥}} (純関数, test可)。"""
    out = collections.defaultdict(lambda: {"n": 0, "sales": 0.0, "profit": 0.0})
    for r in rows2d[1:]:
        def col(i):
            return r[i] if len(r) > i else ""
        if not (col(SALES_COL["item"]) or "").strip():
            continue
        d = parse_date(col(SALES_COL["date"]))
        if not d or d < since:
            continue
        c = norm_cat(col(SALES_COL["cat"]))
        out[c]["n"] += 1
        out[c]["sales"] += money(col(SALES_COL["price"]))
        out[c]["profit"] += money(col(SALES_COL["profit"]))
    return dict(out)


def shelf_by_category(live_rows, cat_by_itemid):
    """生きている出品 → {カテゴリ: 棚$}。ミラーは親 (US) のカテゴリに足す (純関数, test可)。"""
    us_cat = {}
    for r in live_rows:
        if (r.get("Listing site") or "").strip() == "US":
            c = cat_by_itemid.get((r.get("Item number") or "").strip())
            if c:
                us_cat[LF._title_key(r.get("Title"))] = norm_cat(c)
    out = collections.Counter()
    seen = set()
    for r in live_rows:
        i = (r.get("Item number") or "").strip()
        if i in seen:
            continue
        seen.add(i)
        site = (r.get("Listing site") or "").strip()
        if site == "US":
            c = cat_by_itemid.get(i)
            c = norm_cat(c) if c else "(未分類)"
        else:
            c = us_cat.get(LF._title_key(r.get("Title")), "(親が不明)")
        out[c] += money(r.get("Current price"))
    return dict(out)


def _load_live():
    p = sorted(glob.glob(REPORT_GLOB, recursive=True))
    if not p:
        return []
    done = CE.load_done()
    live, seen = [], set()
    for r in csv.DictReader(open(p[-1], encoding="utf-8-sig", errors="replace")):
        i = (r.get("Item number") or "").strip()
        if not i or i in done or i in seen:
            continue
        seen.add(i)
        live.append(r)
    return live


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=90)
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                                          # noqa: BLE001
        pass
    import gspread
    from google.oauth2.service_account import Credentials
    cr = Credentials.from_service_account_file(
        LF.CREDS_PATH, scopes=["https://www.googleapis.com/auth/spreadsheets",
                               "https://www.googleapis.com/auth/drive"])
    gc = gspread.authorize(cr)
    cat_by_itemid = {}
    for sid in LF.SHEET_IDS:
        for r in gc.open_by_key(sid).get_worksheet_by_id(LF.SHEET_GID).get_all_values()[1:]:
            iid = (r[1] if len(r) > 1 else "").strip()
            c = (r[17] if len(r) > 17 else "").strip()
            if iid.isdigit() and c:
                cat_by_itemid[iid] = c
    sales_rows = gc.open_by_key(SALES_SHEET_ID).get_worksheet_by_id(SALES_GID).get_all_values()

    since = datetime.date.today() - datetime.timedelta(days=a.days)
    sales = sales_by_category(sales_rows, since)
    shelf = shelf_by_category(_load_live(), cat_by_itemid)
    tot_shelf = sum(shelf.values())
    tot_profit = sum(v["profit"] for v in sales.values())
    print(f"=== 棚の配分 vs 稼いだ利益 (直近{a.days}日) ===")
    print(f"棚 合計 ${tot_shelf:,.0f} / 利益 合計 ¥{tot_profit:,.0f}\n")
    print(f"{'カテゴリ':16s}{'棚$':>10}{'棚%':>6}{'売れた':>6}{'利益¥':>10}{'利益%':>7}{'棚$1000あたり利益¥':>20}")
    keys = sorted(set(shelf) | set(sales), key=lambda k: -(sales.get(k, {}).get("profit", 0)))
    for k in keys:
        sv = shelf.get(k, 0.0)
        s = sales.get(k, {"n": 0, "profit": 0.0})
        roi = (s["profit"] / sv * 1000) if sv else 0.0
        print(f"{k[:14]:16s}{sv:10,.0f}{(sv/tot_shelf*100 if tot_shelf else 0):5.0f}%"
              f"{s['n']:6d}{s['profit']:10,.0f}{(s['profit']/tot_profit*100 if tot_profit else 0):6.0f}%"
              f"{roi:20,.0f}")
    print("\n※ 棚はミラー (UK/AU/CA) を親 US のカテゴリに合算。")
    print("※ 利益は販売実績スプシの営業利益 (円)。売れて消えた出品もここに入る。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
