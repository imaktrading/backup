"""Phase 6: 抜き取り検査の〇マーク (商品管理シート D列).

TEST_HIGH 100件 dry-run の IN_STOCK 判定 76件から random.sample(seed=42) で 20件抽出し、
商品管理シート (gid=851100680) の **D列** に〇を書き込む。

Takaaki さんは商品管理シートを通常通り開いて、20 個の〇行を 1 件ずつ Mercari で目視確認:
  - Mercari で「在庫あり」だった → scraper 正解 (true negative、ノイズ)
  - Mercari で「売切」だった → scraper 漏れ (false negative)

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
LISTINGS_GID = 851100680
INSPECTION_TAB_NAME = "抜き取り検査"  # 旧方式タブ。残存していれば削除
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

    # 旧方式「抜き取り検査」タブ残存していれば削除
    for ws in sh.worksheets():
        if ws.title == INSPECTION_TAB_NAME:
            print(f"  旧 '{INSPECTION_TAB_NAME}' タブ削除 (gid={ws.id})")
            sh.del_worksheet(ws)
            break

    # 商品管理シート worksheet 取得
    listings_ws = None
    for ws in sh.worksheets():
        if ws.id == LISTINGS_GID:
            listings_ws = ws
            break
    if listings_ws is None:
        print(f"  ❌ 商品管理シート (gid={LISTINGS_GID}) 見つかりません")
        sys.exit(1)
    print(f"  商品管理シート: {listings_ws.title} (id={listings_ws.id})")

    # D列 (4 番目) に〇を batch 書込
    cell_updates = []
    for s in sample:
        cell_updates.append({
            "range": f"D{s['row_index']}",
            "values": [["〇"]],
        })
    listings_ws.batch_update(cell_updates, value_input_option="USER_ENTERED")
    print(f"  D列〇書込完了: {len(sample)} 件")
    print()
    print(f"  商品管理シート URL:")
    print(f"  https://docs.google.com/spreadsheets/d/{TEST_HIGH_ID}/edit#gid={LISTINGS_GID}")
    print()
    print(f"=== 〇付与した 20 行 (row_index 順) ===")
    for s in sample:
        print(f"  row{s['row_index']:>3}  {s['item_id']:>14}  {s['url']}")
        print(f"           title: {s['title'][:50]}")


if __name__ == "__main__":
    main()
