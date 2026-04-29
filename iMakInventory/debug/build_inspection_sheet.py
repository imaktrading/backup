"""Phase 6: 抜き取り検査シート構築.

TEST_HIGH 100件 dry-run の IN_STOCK 判定 76件から random.sample(seed=42) で 20件抽出し、
TEST_HIGH spreadsheet に「抜き取り検査」シートを追加する。

Takaaki さんが目視結果を埋める → false negative 率を測定する用途。

シート構成:
  A: row (商品管理シートでの 1-based 行)
  B: item_id (eBay listing ID)
  C: URL (Mercari)
  D: 判定結果 (Inventory が出した IN_STOCK)
  E: 目視結果 (Takaaki さんが埋める: IN_STOCK / SOLD / DELETED など)
  F: 備考 (Takaaki さん任意)

実行:
  python debug/build_inspection_sheet.py
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sheet_updater import open_sheet_by_id, CREDS_PATH, SCOPES
import gspread
from google.oauth2.service_account import Credentials


TEST_HIGH_ID = "1oDjQC8WN_3WC2InPHAV-hPKmsa96rdNd4jxbGBzDimc"
LATEST_LOG = ROOT / "decision_log" / "listings_HIGH_20260429_221600.jsonl"
INSPECTION_TAB_NAME = "抜き取り検査"
SAMPLE_N = 20
SEED = 42


def collect_in_stock_rows(log_path: Path) -> list:
    """decision_log から Mercari かつ in_stock 判定の行を抽出."""
    rows = []
    with open(log_path, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r.get("supplier") != "mercari":
                continue
            if r.get("error"):
                continue
            if r.get("is_sold"):
                continue
            rows.append({
                "row_index": r["row_index"],
                "item_id": r.get("item_id", ""),
                "url": r.get("url", ""),
                "title": r.get("title", ""),
                "raw_status": r.get("raw_status", ""),
            })
    return rows


def main():
    print(f"=== Phase 6: 抜き取り検査シート構築 ===\n")
    print(f"  decision_log: {LATEST_LOG}")
    if not LATEST_LOG.exists():
        print(f"  ❌ log not found")
        sys.exit(1)

    in_stock_rows = collect_in_stock_rows(LATEST_LOG)
    print(f"  in_stock 判定 (Mercari): {len(in_stock_rows)} 件")

    if len(in_stock_rows) < SAMPLE_N:
        print(f"  ⚠️ 候補 {len(in_stock_rows)} < SAMPLE_N {SAMPLE_N}、全件採用")
        sample = in_stock_rows
    else:
        rng = random.Random(SEED)
        sample = rng.sample(in_stock_rows, SAMPLE_N)
    sample.sort(key=lambda r: r["row_index"])
    print(f"  抽出: {len(sample)} 件 (seed={SEED})\n")

    # spreadsheet open
    sh = open_sheet_by_id(TEST_HIGH_ID)
    print(f"  open: {sh.title}")

    # 既存「抜き取り検査」タブがあれば削除して新規作成 (再実行可能性)
    existing = None
    for ws in sh.worksheets():
        if ws.title == INSPECTION_TAB_NAME:
            existing = ws
            break
    if existing is not None:
        print(f"  既存 '{INSPECTION_TAB_NAME}' 削除")
        sh.del_worksheet(existing)

    new_ws = sh.add_worksheet(title=INSPECTION_TAB_NAME, rows=str(len(sample) + 5), cols="6")
    print(f"  新規 worksheet 作成: {INSPECTION_TAB_NAME} (id={new_ws.id})")

    # ヘッダ + データ書込
    headers = ["row", "item_id", "URL", "判定結果", "目視結果", "備考"]
    values = [headers]
    for s in sample:
        values.append([
            str(s["row_index"]),
            s["item_id"],
            s["url"],
            "IN_STOCK",
            "",  # 目視結果 (空欄)
            "",  # 備考 (空欄)
        ])
    new_ws.update(values=values, range_name="A1", value_input_option="USER_ENTERED")
    print(f"  書込完了: {len(sample) + 1} 行 (header 含む)")
    print()
    print(f"  シート URL: https://docs.google.com/spreadsheets/d/{TEST_HIGH_ID}/edit#gid={new_ws.id}")
    print()
    print(f"=== サンプル先頭 5 件 ===")
    for s in sample[:5]:
        print(f"  row{s['row_index']:>3} {s['item_id']:>14} {s['url'][:55]} title={s['title'][:30]}")


if __name__ == "__main__":
    main()
