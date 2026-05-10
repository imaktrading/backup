#!/usr/bin/env python3
"""monthly_report — eBay seller PDCA の Check 事後 集計.

集計内容:
  1. カテゴリ別 sold 数 / 売上 / 営業利益 / active 数 / sell-through rate
  2. TOP 売れ筋商品 (商品名 keyword 集計、上位 20)
  3. 死蔵 listing 候補 (active 出品済 + 90 日以上 sold ゼロ)

出力:
  販売実績 spreadsheet (1MufEUw...) の「月次レポート」タブを上書き.
  履歴は別タブ「月次履歴」に 1 行追加 (月次 KPI 推移).

使い方:
  python monthly_report.py            # 当月集計
  python monthly_report.py 2026-04    # 指定月集計
"""
from __future__ import annotations

import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import gspread
from google.oauth2.service_account import Credentials

WORKSPACE = Path(__file__).resolve().parent.parent
CREDS_PATH = WORKSPACE / "double-hold-421922-7c0d38d3f73d.json"

# データソース
SALES_SHEET_ID = "1MufEUweIJcLv-NwT3KZsEJ_k_yl1rKryaqBZjUH7c2U"
SALES_GID = 1814510799  # 販売実績
HIGHT_SHEET_ID = "19kj8NqWHIGP1ptQDeGePw077hpdl6dNOO-v2J10HCjk"
HIGHT_GID = 851100680  # 商品管理シート (統合Hight)

# 出力先 (販売実績 spreadsheet 内のタブ)
REPORT_TAB = "月次レポート"
HISTORY_TAB = "月次履歴"

# 死蔵判定: 出品から N 日以上 sold なし
STALE_DAYS = 90


def _gs_client():
    creds = Credentials.from_service_account_file(
        str(CREDS_PATH),
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    return gspread.authorize(creds)


def _parse_money(s):
    """'¥1,234' / '$12.34' / '1234' → float"""
    if not s:
        return 0.0
    import re as _re
    cleaned = _re.sub(r"[^\d.\-]", "", str(s))
    try:
        return float(cleaned) if cleaned else 0.0
    except ValueError:
        return 0.0


def _parse_date(s):
    """'2026/05/01' / '2026-05-01' / '2026年5月1日' 等 → datetime or None"""
    if not s:
        return None
    s = str(s).strip()
    import re as _re
    # YYYY/MM/DD or YYYY-MM-DD
    m = _re.match(r"(\d{4})[/\-年](\d{1,2})[/\-月](\d{1,2})", s)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    return None


def fetch_sales(month_filter=None):
    """販売実績 sheet から sold 履歴取得.

    Args:
        month_filter: "YYYY-MM" 指定で当月のみ. None なら全期間.

    Returns:
        list of dict {item_id, name, sale_date, price, profit, category}
    """
    gc = _gs_client()
    sh = gc.open_by_key(SALES_SHEET_ID)
    ws = sh.get_worksheet_by_id(SALES_GID)
    all_vals = ws.get_all_values()
    if not all_vals or len(all_vals) < 2:
        return []
    sales = []
    for row in all_vals[1:]:
        row = list(row) + [""] * (20 - len(row))
        item_id = row[1].strip()
        name = row[2].strip()
        date = _parse_date(row[4])
        price = _parse_money(row[6])
        profit = _parse_money(row[15])
        category = row[17].strip() or "その他"
        if not item_id and not name:
            continue
        if month_filter and date:
            if date.strftime("%Y-%m") != month_filter:
                continue
        sales.append({
            "item_id": item_id,
            "name": name,
            "sale_date": date,
            "price": price,
            "profit": profit,
            "category": category,
        })
    return sales


def fetch_active_listings():
    """統合Hight から出品中 (B列 ItemID 入) の行取得.

    Returns:
        list of dict {url, item_id, title, category, added_date}
    """
    gc = _gs_client()
    sh = gc.open_by_key(HIGHT_SHEET_ID)
    ws = sh.get_worksheet_by_id(HIGHT_GID)
    all_vals = ws.get('A2:U' + str(ws.row_count))
    actives = []
    for row in all_vals:
        row = list(row) + [""] * (21 - len(row))
        url = row[0].strip()
        item_id = row[1].strip()
        title = row[2].strip()
        sold = row[3].strip()
        category = row[17].strip()
        added = _parse_date(row[20]) if len(row) > 20 else None
        if not url or not item_id:
            continue
        # メルカリ売切 (D列 ✓) は出品取下げ済の可能性 → 除外
        if sold:
            continue
        actives.append({
            "url": url,
            "item_id": item_id,
            "title": title,
            "category": category or "その他",
            "added_date": added,
        })
    return actives


def aggregate_by_category(sales, actives):
    """カテゴリ別集計."""
    cat = defaultdict(lambda: {
        "sold_count": 0, "revenue": 0.0, "profit": 0.0, "active_count": 0,
    })
    for s in sales:
        cat[s["category"]]["sold_count"] += 1
        cat[s["category"]]["revenue"] += s["price"]
        cat[s["category"]]["profit"] += s["profit"]
    for a in actives:
        cat[a["category"]]["active_count"] += 1
    # sell-through rate (sold / active)
    rows = []
    for c, d in sorted(cat.items(), key=lambda x: -x[1]["profit"]):
        active = d["active_count"]
        sold = d["sold_count"]
        st_rate = (sold / active * 100) if active > 0 else 0
        avg_profit = (d["profit"] / sold) if sold > 0 else 0
        rows.append([
            c, sold, active,
            f"{st_rate:.1f}%",
            f"${d['revenue']:.2f}",
            f"¥{d['profit']:,.0f}",
            f"¥{avg_profit:,.0f}",
        ])
    return rows


def top_selling_keywords(sales, top_n=20):
    """商品名 keyword 集計で TOP 売れ筋抽出."""
    import re as _re
    kw_count = defaultdict(int)
    kw_profit = defaultdict(float)
    for s in sales:
        # キーワード抽出: 大文字英語 + 4 文字以上の単語
        words = _re.findall(r"[A-Z][a-zA-Z]{3,}", s["name"])
        for w in set(words):
            kw_count[w] += 1
            kw_profit[w] += s["profit"]
    rows = []
    for kw, cnt in sorted(kw_count.items(), key=lambda x: -x[1])[:top_n]:
        rows.append([kw, cnt, f"¥{kw_profit[kw]:,.0f}", f"¥{kw_profit[kw]/cnt:,.0f}"])
    return rows


def stale_listings(actives, sales, stale_days=STALE_DAYS):
    """死蔵 listing 検出: active 出品 + 売れた履歴なし + 出品から N 日経過."""
    sold_item_ids = {s["item_id"] for s in sales if s["item_id"]}
    sold_titles = {s["name"] for s in sales if s["name"]}
    threshold = datetime.now() - timedelta(days=stale_days)
    stale = []
    for a in actives:
        if a["item_id"] in sold_item_ids:
            continue
        if a["title"] in sold_titles:
            continue
        if a["added_date"] and a["added_date"] > threshold:
            continue  # 90 日経ってない
        days = (datetime.now() - a["added_date"]).days if a["added_date"] else "?"
        stale.append([
            a["category"], a["item_id"], a["title"][:50],
            a["added_date"].strftime("%Y-%m-%d") if a["added_date"] else "?",
            days,
        ])
    return sorted(stale, key=lambda x: -(x[4] if isinstance(x[4], int) else 0))


def write_to_sheet(cat_rows, top_rows, stale_rows, month_label):
    """販売実績 spreadsheet の「月次レポート」タブに上書き、履歴タブに追記."""
    gc = _gs_client()
    sh = gc.open_by_key(SALES_SHEET_ID)
    # レポートタブ確保 (なければ作成)
    try:
        ws = sh.worksheet(REPORT_TAB)
        ws.clear()
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet(title=REPORT_TAB, rows=200, cols=10)
    body = []
    body.append([f"📊 月次レポート ({month_label})", "", "", "", "", "", ""])
    body.append([f"生成: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", "", "", "", "", "", ""])
    body.append([])
    body.append(["▼ カテゴリ別 KPI"])
    body.append(["カテゴリ", "Sold 数", "Active 数", "Sell-through", "売上 ($)", "利益 (¥)", "平均利益 (¥)"])
    body.extend(cat_rows)
    # 合計行
    total_sold = sum(r[1] for r in cat_rows)
    total_active = sum(r[2] for r in cat_rows)
    total_profit = sum(int(str(r[5]).replace("¥", "").replace(",", "")) for r in cat_rows)
    body.append(["合計", total_sold, total_active, "", "", f"¥{total_profit:,}", ""])
    body.append([])
    body.append(["▼ TOP 売れ筋キーワード (商品名から)"])
    body.append(["キーワード", "Sold 数", "総利益 (¥)", "平均利益 (¥)"])
    body.extend(top_rows)
    body.append([])
    body.append([f"▼ 死蔵リスト (出品 {STALE_DAYS}+ 日 sold ゼロ)"])
    body.append(["カテゴリ", "ItemID", "タイトル", "出品日", "経過日数"])
    body.extend(stale_rows[:50])  # 上位 50 件のみ
    if len(stale_rows) > 50:
        body.append([f"... 他 {len(stale_rows) - 50} 件"])
    ws.update(range_name="A1", values=body, value_input_option="USER_ENTERED")
    print(f"📝 シート書込: {REPORT_TAB} ({len(body)} 行)")
    # 月次履歴タブに 1 行追加
    try:
        hws = sh.worksheet(HISTORY_TAB)
    except gspread.exceptions.WorksheetNotFound:
        hws = sh.add_worksheet(title=HISTORY_TAB, rows=200, cols=10)
        hws.update(range_name="A1", values=[[
            "月", "総 Sold 数", "総 Active 数", "総売上 ($)", "総利益 (¥)", "目標 (¥)", "達成率",
        ]])
    target = 100000  # ¥10万 目標
    achievement = f"{total_profit / target * 100:.1f}%" if total_profit else "0.0%"
    next_row = len(hws.get_all_values()) + 1
    hws.update(range_name=f"A{next_row}", values=[[
        month_label, total_sold, total_active,
        f"${sum(_parse_money(r[4][1:]) for r in cat_rows):.2f}",
        f"¥{total_profit:,}", f"¥{target:,}", achievement,
    ]])
    print(f"📝 履歴追記: {HISTORY_TAB} ({month_label})")


def main():
    month = datetime.now().strftime("%Y-%m")
    if len(sys.argv) > 1:
        month = sys.argv[1]
    print(f"=== 月次レポート ({month}) ===\n")

    print("📊 販売実績取得中...")
    sales = fetch_sales(month_filter=month)
    print(f"  {len(sales)} 件 sold (当月)")

    print("📦 統合Hight 取得中...")
    actives = fetch_active_listings()
    print(f"  {len(actives)} 件 active")

    print("\n=== カテゴリ別 KPI ===")
    cat_rows = aggregate_by_category(sales, actives)
    print(f"{'カテゴリ':<15} {'Sold':>5} {'Active':>6} {'ST%':>6} {'売上($)':>10} {'利益(¥)':>12}")
    for r in cat_rows:
        print(f"{r[0]:<15} {r[1]:>5} {r[2]:>6} {r[3]:>6} {r[4]:>10} {r[5]:>12}")

    print("\n=== TOP 売れ筋キーワード ===")
    top_rows = top_selling_keywords(sales, top_n=20)
    for r in top_rows[:10]:
        print(f"  {r[0]:<20} sold {r[1]:>3} 利益 {r[2]}")

    print(f"\n=== 死蔵 listing ({STALE_DAYS}+ 日) ===")
    stale_rows = stale_listings(actives, sales, stale_days=STALE_DAYS)
    print(f"  {len(stale_rows)} 件死蔵候補")
    for r in stale_rows[:5]:
        print(f"  {r[0]:<8} {r[1]:<15} {r[2][:40]:<40} {r[3]} ({r[4]}日)")

    print("\n📝 GSheet 書込中...")
    write_to_sheet(cat_rows, top_rows, stale_rows, month)
    print("\n✅ 完了")


if __name__ == "__main__":
    main()
