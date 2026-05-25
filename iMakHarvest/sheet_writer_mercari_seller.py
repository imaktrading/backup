"""sheet_writer_mercari_seller - 中間スプシ (= seller staging) に seller_<id> タブで append.

依頼書 (2026-05-26) sec 3 / 4 に従う:
  - 出力先 = 固定 spreadsheet `1hTdFVGkni4Ih4kZGsBgiCKxpTlOeoO_wJdk8Ek5n41Q`
  - タブ名 = `seller_<seller_id>` (= 自動 create、 既存あり時は append)
  - dedup = タブ単位 (= seller_id ごと独立、 mercari item ID `m\\d+` key)
  - 別 seller タブが同 item 持ってても両方残す (= scope クロスしない)

中間スプシの用途 = ステージング:
  - ユーザー目視確認後、 手動で HIGH/LOW に転記
  - 直接 HIGH/LOW に流さない (= 大量 false 投入の連鎖事故防止)
  - 「出品の正確性」 原則 (= ユーザー目視 verify 工程) 担保
"""
from __future__ import annotations

import os
from typing import Optional

import gspread
from google.oauth2.service_account import Credentials

from sheet_writer import (
    CREDS_PATH,
    SCOPES,
    WITH_AUX_COLUMN_COUNT,
    _build_row,
    dedupe_key,
)

# 中間スプシ ID (= 依頼書 sec 3 で指定)
SELLER_STAGING_SHEET_ID = "1hTdFVGkni4Ih4kZGsBgiCKxpTlOeoO_wJdk8Ek5n41Q"

# タブ作成時のデフォルト サイズ (= 33 列固定で auxiliary_urls 含めて入る)
DEFAULT_NEW_TAB_ROWS = 1000
DEFAULT_NEW_TAB_COLS = 33


def open_seller_staging_sheet():
    """中間スプシ open (= service account 認証)."""
    if not os.path.exists(CREDS_PATH):
        raise FileNotFoundError(f"サービスアカウント JSON が見つかりません: {CREDS_PATH}")
    creds = Credentials.from_service_account_file(CREDS_PATH, scopes=SCOPES)
    gc = gspread.authorize(creds)
    return gc.open_by_key(SELLER_STAGING_SHEET_ID)


def get_or_create_seller_tab(sh, seller_id: str):
    """`seller_<id>` タブを取得、 なければ create.

    Returns: gspread worksheet
    """
    tab_name = f"seller_{seller_id}"
    try:
        return sh.worksheet(tab_name)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(
            title=tab_name, rows=DEFAULT_NEW_TAB_ROWS, cols=DEFAULT_NEW_TAB_COLS,
        )
        return ws


def read_existing_dedupe_keys_in_tab(ws) -> set[str]:
    """タブ内既存行から dedupe key set 構築 (= A 列 URL を sheet_writer.dedupe_key で変換)."""
    all_values = ws.get_all_values()
    if not all_values:
        return set()
    keys: set[str] = set()
    for row in all_values:
        if not row:
            continue
        url = (row[0] or "").strip()
        k = dedupe_key(url)
        if k:
            keys.add(k)
    return keys


def append_seller_items(
    seller_id: str,
    items: list[dict],
    column_count: int = WITH_AUX_COLUMN_COUNT,
) -> dict:
    """中間スプシの seller_<id> タブに items を append (タブ単位 dedup).

    Args:
        seller_id: 数字文字列 (= URL から抽出済)
        items: mercari_seller.group_items_by_card_id 戻り値 (= auxiliary_urls 含む可)
        column_count: 書込列数 default 33 (= AC-AG 含む)

    Returns:
        {
            "tab": "seller_<id>",
            "appended": N,
            "skipped_existing": M,
            "input": K,
        }
    """
    if not items:
        return {"tab": f"seller_{seller_id}", "appended": 0, "skipped_existing": 0, "input": 0}

    sh = open_seller_staging_sheet()
    ws = get_or_create_seller_tab(sh, seller_id)
    existing = read_existing_dedupe_keys_in_tab(ws)

    new_rows: list[list[str]] = []
    skipped = 0
    seen_in_batch: set[str] = set()
    for it in items:
        url = (it.get("url") or "").strip()
        if not url:
            skipped += 1
            continue
        key = dedupe_key(url)
        if not key:
            skipped += 1
            continue
        if key in existing or key in seen_in_batch:
            skipped += 1
            continue
        seen_in_batch.add(key)

        row = _build_row(it)
        if len(row) < column_count:
            row += [""] * (column_count - len(row))
        new_rows.append(row[:column_count])

    if new_rows:
        ws.append_rows(new_rows, value_input_option="USER_ENTERED")

    return {
        "tab": f"seller_{seller_id}",
        "appended": len(new_rows),
        "skipped_existing": skipped,
        "input": len(items),
    }
