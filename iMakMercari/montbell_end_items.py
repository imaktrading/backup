#!/usr/bin/env python3
"""モンベル管理シート → eBay取下げCSV生成

条件に合致する行をeBay FileExchange EndItem形式のCSVで出力:
  - 売り切れ=○ かつ itemID あり
  - 取下げ推奨=○ かつ itemID あり

出力: iMakHQ/csv_output/montbell_end_items_YYYYMMDD_HHMMSS.csv

使い方: python montbell_end_items.py
"""
import csv
import os
import sys
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "..", "iMakHQ", "csv_output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# スクレイパーと同じスプシ設定
SHEET_ID = "1LDlJuEbqy3wmwRSlTqgCzqcZxzu8phO4PITm7nYRoNw"
SHEET_GID = 851100680
GSHEET_CREDS = os.path.join(SCRIPT_DIR, "..", "double-hold-421922-7c0d38d3f73d.json")

COL_MAP = {
    "URL": 1, "itemID": 2, "タイトル": 3, "売り切れ": 4, "状態": 5,
    "商品価格": 6, "写真URL": 7, "商品説明": 8, "Title": 9, "Description": 10,
    "出品する価格（ドル）": 11, "ConditionID": 12, "価格上昇有無": 13,
    "仕入れ価格（円）": 14, "売り切れチェック時間": 15,
    "サイズ": 16, "カラー": 17, "在庫数": 18, "商品ID": 19,
    "取下げ推奨": 20,
}


def main():
    print("=== モンベル 取下げCSV生成 ===\n")
    import gspread
    from google.oauth2.service_account import Credentials
    creds = Credentials.from_service_account_file(
        GSHEET_CREDS, scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(SHEET_ID)
    ws = sh.get_worksheet_by_id(SHEET_GID)
    all_vals = ws.get_all_values()

    targets = []
    for i, row in enumerate(all_vals[1:], start=2):
        def col(name):
            idx = COL_MAP[name] - 1
            return row[idx] if len(row) > idx else ""
        item_id = col("itemID").strip()
        sold_out = col("売り切れ").strip()
        takedown_suggest = col("取下げ推奨").strip()
        if not item_id:
            continue  # eBay出品されてない行はスキップ
        reason = None
        if sold_out == "○":
            reason = "NotAvailable (ソース売切れ)"
        elif takedown_suggest == "○":
            reason = "OtherListingError (スクレイプ失敗、要確認)"
        if reason:
            targets.append({
                "row": i,
                "itemID": item_id,
                "product_id": col("商品ID"),
                "size": col("サイズ"),
                "color": col("カラー"),
                "reason": reason,
            })

    print(f"取下げ対象: {len(targets)}件")
    if not targets:
        print("該当なし、CSV生成スキップ")
        return

    # eBay FileExchange形式のEndItem CSV
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = os.path.join(OUTPUT_DIR, f"montbell_end_items_{ts}.csv")
    with open(out, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, quoting=csv.QUOTE_NONNUMERIC)
        writer.writerow(["Action", "ItemID", "EndCode"])
        for t in targets:
            end_code = "NotAvailable" if "NotAvailable" in t["reason"] else "OtherListingError"
            writer.writerow(["EndItem", t["itemID"], end_code])

    print(f"\n✅ 出力: {out}")
    print("\n=== 詳細（ログ） ===")
    for t in targets[:20]:
        print(f"  [行{t['row']}] itemID={t['itemID']} 商品{t['product_id']}/{t['size']}/{t['color']} → {t['reason']}")
    if len(targets) > 20:
        print(f"  ... 他 {len(targets)-20} 件")

    print(f"\n次のステップ:")
    print(f"  1. eBay Seller Hub > File Exchange > Upload")
    print(f"  2. 上記CSVをアップロード → 一括取下げ")


if __name__ == "__main__":
    main()
