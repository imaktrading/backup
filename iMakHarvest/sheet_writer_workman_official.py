"""sheet_writer_workman_official - ★公式在庫要チェック シート1 への Workman 投入専用 writer.

Phase 2 (v2 仕様、commit `fdb642d` Phase 1e の HIGH/LOW 投入から移行) で確定:
  - 投入先 = `101KL6KxMugKqZeSp2W5L2ykTvT0Zwd3RzlfsHgiJsg0` シート1 (gid=0)
  - 書込列 = B (title) + F (仕入元 URL) のみ
  - 他列 (A FLG / C item ID / E ebay URL / G CHK date 等) は touch しない
  - dedupe = F 列 URL から parent_mpn 抽出して同一判定
  - 既存 supplier (UNIQLO 等) 行と共存可 (parent_mpn 抽出不能なら別 key で衝突なし)

設計原則 (sheet_writer.py / sheet_writer_amazon.py と同じ独立分離方針):
  - 既存スプシ・列構成を一切壊さない
  - 既存行は絶対に上書きしない (新規 append のみ)
  - 失敗時は raise (caller が retry 判断)

UNIQLO 共通化の余地:
  Phase 2 では Workman 専用実装。UNIQLO 経路 (5/16 議論中、保留状態) が確定後、
  base module 化リファクタを別 phase で実施 (v2 仕様 section 1)。
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Optional  # noqa: F401  (将来拡張用)

import gspread
from google.oauth2.service_account import Credentials

from sheet_writer import _WORKMAN_MPN_RE, dedupe_key  # 既存 dedupe ロジック流用

CREDS_PATH = r"c:\dev\iMak\double-hold-421922-7c0d38d3f73d.json"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# ★公式在庫要チェック スプシ (Phase 2 投入先、v2 仕様 section 1 確定)
OFFICIAL_SHEET_ID = "101KL6KxMugKqZeSp2W5L2ykTvT0Zwd3RzlfsHgiJsg0"
OFFICIAL_GID = 0  # シート1 (UNIQLO/Workman 共有予定の URL リスト)

# シート1 列マッピング (1-based、v2 仕様 section 4.1 確定)
COL_FLG = 1            # A: FLG (1=除外、空=active) — 人手 / Inventory
COL_TITLE = 2          # B: title — Harvest 投入時記入 ←
COL_ITEM_ID = 3        # C: item ID (eBay listing_id) — 出品くんが update
COL_EBAY_URL = 5       # E: ebay URL — 出品くんが update
COL_URL = 6            # F: 仕入元 URL — Harvest 投入時記入 ←
COL_CHK_DATE = 7       # G: CHK date — Inventory が update

# 書込み列数 = 7 (A〜G)。H 以降は既存スプシで使用中だが Harvest は touch しない。
WORKMAN_OFFICIAL_COLUMN_COUNT = 7


def open_sheet_by_id(spreadsheet_id: str = OFFICIAL_SHEET_ID):
    """サービスアカウント認証 → spreadsheet オブジェクト返却."""
    if not os.path.exists(CREDS_PATH):
        raise FileNotFoundError(f"サービスアカウント JSON が見つかりません: {CREDS_PATH}")
    creds = Credentials.from_service_account_file(CREDS_PATH, scopes=SCOPES)
    gc = gspread.authorize(creds)
    return gc.open_by_key(spreadsheet_id)


def get_official_worksheet(sh, gid: int = OFFICIAL_GID):
    """シート1 (gid 一致) を取得. 無ければ最初のシートにフォールバック."""
    for ws in sh.worksheets():
        if ws.id == gid:
            return ws
    return sh.get_worksheet(0)


def read_existing_dedupe_keys(ws) -> set[str]:
    """既存行から デデュープ key set を取得 (F 列 URL のみ参照).

    F 列の URL から parent_mpn 抽出 → `workman:<mpn>` key。
    UNIQLO 等他 supplier の URL は parent_mpn 抽出できないので別 key になり衝突しない。
    """
    all_values = ws.get_all_values()
    if len(all_values) < 2:
        return set()
    keys: set[str] = set()
    for row in all_values[1:]:  # ヘッダー行 skip
        if len(row) >= COL_URL:
            url = (row[COL_URL - 1] or "").strip()
            k = dedupe_key(url)
            if k:
                keys.add(k)
    return keys


def _build_workman_row(item: dict) -> list:
    """item dict → シート1 用 1 行 (7 列、B 列 title + F 列 URL のみ値あり).

    他列 (A FLG / C item ID / D / E ebay URL / G CHK date) は空文字。
    """
    title = str(item.get("title") or "").strip()
    url = str(item.get("url") or "").strip()

    row = [""] * WORKMAN_OFFICIAL_COLUMN_COUNT  # A〜G
    # COL_FLG (A) = 空 (active)
    row[COL_TITLE - 1] = title
    # COL_ITEM_ID (C) = 空 (出品くんが update)
    # COL_EBAY_URL (E) = 空 (出品くんが update)
    row[COL_URL - 1] = url
    # COL_CHK_DATE (G) = 空 (Inventory が update)
    return row


def append_workman_urls(
    ws,
    items: list[dict],
) -> dict:
    """items を シート1 に append (parent_mpn dedupe + title/URL のみ書込).

    Args:
        ws:    gspread worksheet (シート1)
        items: [
                 {"url": "https://workman.jp/shop/g/g<mpn>/", "title": "商品名", ...},
                 ...
               ]
        title / url のいずれかが空欄の item は **fail-closed で skip** (v2 仕様確定)。

    Returns: {"appended": N, "skipped_existing": M, "skipped_invalid": K, "input": L}
    """
    if not items:
        return {"appended": 0, "skipped_existing": 0, "skipped_invalid": 0, "input": 0}

    existing = read_existing_dedupe_keys(ws)

    new_rows = []
    skipped_existing = 0
    skipped_invalid = 0
    seen_in_batch: set[str] = set()
    for it in items:
        url = (it.get("url") or "").strip()
        title = (it.get("title") or "").strip()
        # fail-closed: title 空 or URL 空 → skip
        if not url or not title:
            skipped_invalid += 1
            continue
        key = dedupe_key(url)
        # parent_mpn 抽出不能 → invalid 扱いで skip
        if not key or not key.startswith("workman:"):
            skipped_invalid += 1
            continue
        if key in existing or key in seen_in_batch:
            skipped_existing += 1
            continue
        seen_in_batch.add(key)

        row = _build_workman_row(it)
        new_rows.append(row)

    if not new_rows:
        return {
            "appended": 0,
            "skipped_existing": skipped_existing,
            "skipped_invalid": skipped_invalid,
            "input": len(items),
        }

    # 末尾に append (既存行は touch しない)
    ws.append_rows(new_rows, value_input_option="USER_ENTERED")

    return {
        "appended": len(new_rows),
        "skipped_existing": skipped_existing,
        "skipped_invalid": skipped_invalid,
        "input": len(items),
    }


def write_to_official_sheet(items: list[dict]) -> dict:
    """items を ★公式在庫要チェック シート1 に投入 (Workman 専用).

    入口関数 (CLI / GUI から呼ばれる)。
    """
    sh = open_sheet_by_id(OFFICIAL_SHEET_ID)
    ws = get_official_worksheet(sh, gid=OFFICIAL_GID)
    return append_workman_urls(ws, items)


# ============================================================================
# CLI (動作確認用)
# ============================================================================
if __name__ == "__main__":
    import argparse
    import json
    import sys

    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="JSON file: [{url, title}, ...]")
    args = ap.parse_args()

    with open(args.input, "r", encoding="utf-8") as f:
        items = json.load(f)
    if not isinstance(items, list):
        print("input must be a JSON list", file=sys.stderr)
        sys.exit(1)

    result = write_to_official_sheet(items)
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] result: {result}")
