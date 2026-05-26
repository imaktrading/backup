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

# 中間スプシ内の template タブ名 (= ヘッダー行 / 列幅 / 書式 のコピー元)
TEMPLATE_TAB_NAME = "商品管理シート"

# タブ作成時のデフォルト サイズ (= 33 列で auxiliary_urls AC-AG まで対応)
DEFAULT_NEW_TAB_ROWS = 1000
DEFAULT_NEW_TAB_COLS = 33


def open_seller_staging_sheet():
    """中間スプシ open (= service account 認証)."""
    if not os.path.exists(CREDS_PATH):
        raise FileNotFoundError(f"サービスアカウント JSON が見つかりません: {CREDS_PATH}")
    creds = Credentials.from_service_account_file(CREDS_PATH, scopes=SCOPES)
    gc = gspread.authorize(creds)
    return gc.open_by_key(SELLER_STAGING_SHEET_ID)


def _col_to_letter(col: int) -> str:
    """1-based col 番号 → letter (A, B, ..., Z, AA, AB, ...)."""
    letters = ""
    n = col
    while n > 0:
        n, r = divmod(n - 1, 26)
        letters = chr(ord("A") + r) + letters
    return letters


def _get_template_header(sh) -> list[str]:
    """中間スプシ内 template タブ (= TEMPLATE_TAB_NAME) の row 1 ヘッダーを取得.

    template タブが無ければ空 list (= fallback でヘッダーなし運用)。
    """
    try:
        template_ws = sh.worksheet(TEMPLATE_TAB_NAME)
    except gspread.WorksheetNotFound:
        return []
    return template_ws.row_values(1)


def _ensure_header(ws, sh) -> bool:
    """row 1 がヘッダーと一致しない → template ヘッダーを insert.

    既存タブで row 1 がデータ (= URL 行) の場合、 ヘッダー insert して既存データを
    row 2 以降にシフト。 row 1 が既にヘッダー (= 先頭セル == 'URL' 等) なら何もしない。

    Returns: True = ヘッダー insert した、 False = 既にヘッダーありで何もしない
    """
    expected_header = _get_template_header(sh)
    if not expected_header:
        return False  # template ない → 何もしない
    current_row1 = ws.row_values(1)
    # row 1 の先頭セルが期待ヘッダーの先頭と一致 → 既にヘッダー
    if current_row1 and current_row1[0] == expected_header[0]:
        return False
    # ヘッダーなし → row 1 に insert (= 既存データは row 2 以降にシフト)
    ws.insert_row(expected_header, index=1, value_input_option="USER_ENTERED")
    return True


def _create_from_template(sh, tab_name: str):
    """中間スプシ template「商品管理シート」 タブを複製して `seller_<id>` 化.

    template の format / 列幅 / 書式 / 数式 がそのまま継承される (= duplicate API)。
    template に既存 data row があれば row 2 以降を clear (= ヘッダーのみ残す)。
    template が無い場合 fallback で空タブ作成。
    """
    try:
        template_ws = sh.worksheet(TEMPLATE_TAB_NAME)
    except gspread.WorksheetNotFound:
        return sh.add_worksheet(
            title=tab_name, rows=DEFAULT_NEW_TAB_ROWS, cols=DEFAULT_NEW_TAB_COLS,
        )
    new_ws = template_ws.duplicate(new_sheet_name=tab_name)
    # template の data 行 (row 2 以降) をクリア = ヘッダーのみ残す
    if new_ws.row_count > 1 and new_ws.col_count > 0:
        last_col_letter = _col_to_letter(new_ws.col_count)
        new_ws.batch_clear([f"A2:{last_col_letter}{new_ws.row_count}"])
    return new_ws


def get_or_create_seller_tab(sh, seller_id: str):
    """`seller_<id>` タブを取得、 なければ template「商品管理シート」 を複製して create.

    template による複製で format / 列幅 / 書式 が HIGH/LOW 「商品管理シート」 と整合。
    既存タブでヘッダーが無い場合 (= 旧 logic で create された旧タブ) は ヘッダー insert で追補。

    Returns: gspread worksheet
    """
    tab_name = f"seller_{seller_id}"
    try:
        existing = sh.worksheet(tab_name)
        # 既存タブ → ヘッダー確認 + 必要なら insert
        _ensure_header(existing, sh)
        return existing
    except gspread.WorksheetNotFound:
        # 新規 create (= template 複製)
        return _create_from_template(sh, tab_name)


def read_existing_dedupe_keys_in_tab(ws) -> set[str]:
    """タブ内既存行から dedupe key set 構築 (= A 列 URL を sheet_writer.dedupe_key で変換).

    row 1 はヘッダー行として skip (= 「URL」 等の文字列が dedupe_key 化されないよう)。
    """
    all_values = ws.get_all_values()
    if len(all_values) < 2:
        return set()
    keys: set[str] = set()
    for row in all_values[1:]:  # row 1 (ヘッダー) skip
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
