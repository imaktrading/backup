# -*- coding: utf-8 -*-
"""4 スプシから ItemID → 仕入¥ マッピングを取得して JSON 保存
- HIGHT (19kj8N..., gid=851100680): B列 ItemID, N列 仕入¥
- LOW (1jF9vgg..., gid=851100680): B列 ItemID, N列 仕入¥
- 公式 (101KL6K..., SKU詳細タブ): D列 listing ID, J列 仕入元価格
- 有在庫 (1zbzr1f..., シート2 gid=2025152218): B列 Item number, D列 仕入金額
"""
import gspread
import json
import re
from google.oauth2.service_account import Credentials
from pathlib import Path
from collections import defaultdict

CREDS = Path(r"c:\dev\iMak\double-hold-421922-7c0d38d3f73d.json")
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
OUTPUT = Path(r"c:\tmp\v6_item_costs.json")

gc = gspread.authorize(Credentials.from_service_account_file(str(CREDS), scopes=SCOPES))


def parse_money(s):
    """'¥1,234' / '1234' / '$12' → int(¥) or 0"""
    if not s:
        return 0
    cleaned = re.sub(r"[^\d.]", "", str(s))
    try:
        return int(float(cleaned)) if cleaned else 0
    except ValueError:
        return 0


def fetch_hight_or_low(sheet_id, gid, label):
    """HIGHT / LOW 共通: B列 ItemID, N列 仕入¥ (N 空なら F 列商品価格 fallback), R列 カテゴリ"""
    sh = gc.open_by_key(sheet_id)
    ws = sh.get_worksheet_by_id(gid)
    rows = ws.get_all_values()
    result = {}
    cat_result = {}
    for row in rows[1:]:
        item_id = (row[1] if len(row) > 1 else "").strip()   # B
        cost_n  = (row[13] if len(row) > 13 else "").strip() # N: 仕入れ価格
        cost_f  = (row[5] if len(row) > 5 else "").strip()   # F: 商品価格 (fallback)
        category = (row[17] if len(row) > 17 else "").strip() # R: カテゴリ
        if not item_id:
            continue
        cost = parse_money(cost_n) or parse_money(cost_f)
        if cost > 0:
            result[item_id] = cost
        if category:
            cat_result[item_id] = category
    print(f"[{label}] {len(result)} items (cost), {len(cat_result)} (category)")
    return result, cat_result


def fetch_official():
    """公式 (★公式在庫要チェック) SKU詳細: D列 listing ID, J列 仕入元価格"""
    sh = gc.open_by_key("101KL6KxMugKqZeSp2W5L2ykTvT0Zwd3RzlfsHgiJsg0")
    ws = sh.worksheet("SKU詳細")
    rows = ws.get_all_values()
    # ItemID 単位で集約 (= variation 別 SKU の最初の値を採用 / 同一 ItemID なら同価想定)
    result = {}
    for row in rows[1:]:
        listing_id = (row[3] if len(row) > 3 else "").strip()  # D
        cost_j     = (row[9] if len(row) > 9 else "").strip()   # J
        if not listing_id or not cost_j:
            continue
        cost = parse_money(cost_j)
        if cost > 0 and listing_id not in result:
            result[listing_id] = cost
    print(f"[公式] {len(result)} items")
    return result


def fetch_zaiko():
    """有在庫 シート2: B列 Item number, D列 仕入金額"""
    sh = gc.open_by_key("1zbzr1fifHMAcgJ5n_9CcMXzJASxcvk3DutgOQfNElNA")
    ws = sh.get_worksheet_by_id(2025152218)
    rows = ws.get_all_values()
    result = {}
    for row in rows[3:]:  # row 1-3 ヘッダ
        item_id = (row[1] if len(row) > 1 else "").strip()  # B
        cost_d  = (row[3] if len(row) > 3 else "").strip()  # D
        if not item_id or not cost_d:
            continue
        cost = parse_money(cost_d)
        if cost > 0:
            result[item_id] = cost
    print(f"[有在庫] {len(result)} items")
    return result


def main():
    sources = {}
    cats = {}
    hight_cost, hight_cat = fetch_hight_or_low("19kj8NqWHIGP1ptQDeGePw077hpdl6dNOO-v2J10HCjk", 851100680, "HIGHT")
    low_cost,   low_cat   = fetch_hight_or_low("1jF9vggbfUCddjneROMO2GGN-jTAPRbq6Qe2cbgr37B0", 851100680, "LOW")
    sources["HIGHT"] = hight_cost
    sources["LOW"]   = low_cost
    sources["OFFICIAL"] = fetch_official()
    sources["ZAIKO"]    = fetch_zaiko()

    # カテゴリは HIGHT > LOW 優先 (= 同一 ItemID あれば HIGHT で上書き)
    cat_merged = {}
    cat_merged.update(low_cat)
    cat_merged.update(hight_cat)

    # 統合 (= 同一 ItemID が複数ソースにある場合の優先順: ZAIKO > OFFICIAL > HIGHT > LOW)
    merged = {}
    src_map = {}
    for src in ["LOW", "HIGHT", "OFFICIAL", "ZAIKO"]:
        for k, v in sources[src].items():
            merged[k] = v
            src_map[k] = src

    print()
    print(f"=== 統合 ===")
    print(f"Total unique ItemIDs (cost): {len(merged)}")
    print(f"Total unique ItemIDs (cat) : {len(cat_merged)}")
    src_count = defaultdict(int)
    for v in src_map.values():
        src_count[v] += 1
    for s, c in sorted(src_count.items()):
        print(f"  {s}: {c}")

    # 保存
    data = {"costs": merged, "source": src_map, "categories": cat_merged}
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nSaved: {OUTPUT}")


if __name__ == "__main__":
    main()
