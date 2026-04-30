"""sheet_writer - 収集 URL を Google Sheets に追記 (デデュープ付き).

設計原則:
  - 既存スプシ・列構成を一切壊さない (HIGH/LOW listings シートと同じ列レイアウトを採用)
  - 既出 item_id は再書込しない (B 列 item_id をキーにデデュープ)
  - 失敗時は raise (caller が retry 判断)
  - 既存行は絶対に上書きしない (新規 append のみ)

スプシ列レイアウト (iMakInventory HIGH/LOW listings 互換):
  A: URL          ← Harvest が書込 (新規行)
  B: item_id      ← Harvest が書込 (新規行)
  C: title        ← Harvest が書込可 (Phase 1a では空欄)
  D: 売り切れ     ← iMakInventory が後で書込 (Harvest は空欄のまま)
  E~: その他     ← Harvest は触らない

サービスアカウント認証情報パスは iMakInventory と共通 (CREDS_PATH)。
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Optional

import gspread
from google.oauth2.service_account import Credentials

CREDS_PATH = r"c:\dev\iMak\double-hold-421922-7c0d38d3f73d.json"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# HIGH/LOW listings シートの既知 ID (iMakInventory.sheet_updater と同じ値)
HIGH_SHEET_ID = "19kj8NqWHIGP1ptQDeGePw077hpdl6dNOO-v2J10HCjk"
LOW_SHEET_ID = "1jF9vggbfUCddjneROMO2GGN-jTAPRbq6Qe2cbgr37B0"
LISTINGS_GID = 851100680  # 商品管理シートタブ (HIGH/LOW 共通)

# 列マッピング (1-based)
COL_URL = 1      # A
COL_ITEM_ID = 2  # B
COL_TITLE = 3    # C


def open_sheet_by_id(spreadsheet_id: str):
    """サービスアカウント認証 → spreadsheet オブジェクト返却."""
    if not os.path.exists(CREDS_PATH):
        raise FileNotFoundError(f"サービスアカウント JSON が見つかりません: {CREDS_PATH}")
    creds = Credentials.from_service_account_file(CREDS_PATH, scopes=SCOPES)
    gc = gspread.authorize(creds)
    return gc.open_by_key(spreadsheet_id)


def get_listings_worksheet(sh, gid: int = LISTINGS_GID):
    """商品管理シート (gid 一致) を取得. 無ければ最初のシートにフォールバック."""
    for ws in sh.worksheets():
        if ws.id == gid:
            return ws
    return sh.get_worksheet(0)


def read_existing_item_ids(ws) -> set[str]:
    """ワークシート B 列に既に存在する item_id を全件取得."""
    all_values = ws.get_all_values()
    if len(all_values) < 2:
        return set()
    existing: set[str] = set()
    for row in all_values[1:]:
        if len(row) >= COL_ITEM_ID:
            v = (row[COL_ITEM_ID - 1] or "").strip()
            if v:
                existing.add(v)
    return existing


def append_new_urls(
    ws,
    items: list[dict],
    column_count: int = 3,
) -> dict:
    """items を ws に追記 (既出 item_id は除外).

    Args:
        ws:    gspread worksheet
        items: [{"url", "item_id", "title"?}, ...]
        column_count: 書く列数 (default 3 = A:URL, B:item_id, C:title)

    Returns: {"appended": N, "skipped_existing": M, "input": K}
    """
    if not items:
        return {"appended": 0, "skipped_existing": 0, "input": 0}

    existing = read_existing_item_ids(ws)

    new_rows = []
    skipped = 0
    seen_in_batch: set[str] = set()
    for it in items:
        item_id = (it.get("item_id") or "").strip()
        url = (it.get("url") or "").strip()
        if not item_id or not url:
            skipped += 1
            continue
        if item_id in existing or item_id in seen_in_batch:
            skipped += 1
            continue
        seen_in_batch.add(item_id)
        row = [url, item_id, str(it.get("title") or "")]
        # column_count に満たない場合は空欄で埋める (3 列固定で OK)
        if len(row) < column_count:
            row += [""] * (column_count - len(row))
        new_rows.append(row[:column_count])

    if not new_rows:
        return {"appended": 0, "skipped_existing": skipped, "input": len(items)}

    # 末尾に append (既存行は触らない)
    ws.append_rows(new_rows, value_input_option="USER_ENTERED")

    return {
        "appended": len(new_rows),
        "skipped_existing": skipped,
        "input": len(items),
    }


def write_to_sheet(
    items: list[dict],
    spreadsheet_id: str,
    gid: int = LISTINGS_GID,
) -> dict:
    """items を spreadsheet_id の listings シートに書込 (デデュープ付き append).

    入口関数。caller は spreadsheet_id を選んで呼ぶ。
    """
    sh = open_sheet_by_id(spreadsheet_id)
    ws = get_listings_worksheet(sh, gid=gid)
    return append_new_urls(ws, items)


# ============================================================================
# CLI (動作確認用)
# ============================================================================
if __name__ == "__main__":
    import argparse
    import json
    import sys

    ap = argparse.ArgumentParser()
    ap.add_argument("--sheet-id", required=True, help="HIGH or LOW spreadsheet ID")
    ap.add_argument("--gid", type=int, default=LISTINGS_GID)
    ap.add_argument("--input", required=True, help="JSON file: [{url, item_id, title?}, ...]")
    args = ap.parse_args()

    with open(args.input, "r", encoding="utf-8") as f:
        items = json.load(f)
    if not isinstance(items, list):
        print("input must be a JSON list", file=sys.stderr)
        sys.exit(1)

    result = write_to_sheet(items, spreadsheet_id=args.sheet_id, gid=args.gid)
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] result: {result}")
