"""sheet_writer_mercari_shops - 中間スプシに `shops_<shop_id>` タブで append.

mercari_shops_search 用。 sheet_writer_mercari_seller の機能を流用、
tab 命名と append wrapper のみ差替。

中間スプシ:
  - spreadsheet ID = sheet_writer_mercari_seller.SELLER_STAGING_SHEET_ID (= 同じ)
  - tab 命名:
      * shop_id あり + keyword あり → `shops_<shop_id>_<kw_short>`
      * shop_id あり + keyword なし → `shops_<shop_id>`
      * shop_id なし + keyword あり → `shops_kw_<kw_short>`
  - dedup = タブ単位 (= shop / keyword 組合せごと独立、 shops:<UUID> key)
  - 補仕入 URL (AC-AG) は今フェーズ scope 外 = 必ず空欄
"""
from __future__ import annotations

import re
from typing import Optional

import gspread

from sheet_writer import WITH_AUX_COLUMN_COUNT, _build_row, dedupe_key
from sheet_writer_mercari_seller import (
    _col_to_letter,
    _create_from_template,
    _ensure_header,
    open_seller_staging_sheet,
    read_existing_dedupe_keys_in_tab,
)


def _sanitize_for_tab(s: str, max_len: int = 30) -> str:
    """tab 名 安全化 (= gspread tab name に許される文字に絞り + 長さ制限)."""
    if not s:
        return ""
    # 非英数字 / 非日本語 を _ に置換
    s2 = re.sub(r"[^\w぀-ゟ゠-ヿ一-鿿]", "_", s)
    s2 = re.sub(r"_+", "_", s2).strip("_")
    return s2[:max_len]


def build_shops_tab_name(
    shop_id: Optional[str], keyword: Optional[str] = None
) -> str:
    """shop_id + keyword から tab 名生成.

    - 両方あり → `shops_<shop_id>_<kw_short>`
    - shop_id のみ → `shops_<shop_id>`
    - keyword のみ → `shops_kw_<kw_short>`
    - 両方なし → `shops_unknown`
    """
    sid = (shop_id or "").strip()
    kw = _sanitize_for_tab(keyword or "")
    if sid and kw:
        return f"shops_{sid}_{kw}"
    if sid:
        return f"shops_{sid}"
    if kw:
        return f"shops_kw_{kw}"
    return "shops_unknown"


def get_or_create_shops_tab(
    sh, shop_id: Optional[str], keyword: Optional[str] = None,
):
    """`shops_<...>` タブを取得、 なければ template「商品管理シート」 を複製 create."""
    tab_name = build_shops_tab_name(shop_id, keyword)
    try:
        existing = sh.worksheet(tab_name)
        _ensure_header(existing, sh)
        return existing
    except gspread.WorksheetNotFound:
        return _create_from_template(sh, tab_name)


def append_shops_items(
    items: list[dict],
    shop_id: Optional[str],
    keyword: Optional[str] = None,
    column_count: int = WITH_AUX_COLUMN_COUNT,
) -> dict:
    """中間スプシの shops_<...> タブに items を append (タブ単位 dedup).

    Args:
        items: mercari_shops_search.collect_shops_search_with_details の "items"
        shop_id: search URL から抽出した shop_id (= optional)
        keyword: search URL から抽出した keyword (= optional)
        column_count: 書込列数 default 33

    Returns:
        {
            "tab": str,
            "appended": N,
            "skipped_existing": M,
            "input": K,
        }
    """
    tab_name = build_shops_tab_name(shop_id, keyword)
    if not items:
        return {"tab": tab_name, "appended": 0, "skipped_existing": 0, "input": 0}

    sh = open_seller_staging_sheet()
    ws = get_or_create_shops_tab(sh, shop_id, keyword)
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
        # append_rows の AC 列誤検出対策 (= seller 版と同 fix)
        last_row = len(ws.get_all_values())
        next_row = last_row + 1
        end_col_letter = _col_to_letter(column_count)
        end_row = next_row + len(new_rows) - 1
        ws.update(
            range_name=f"A{next_row}:{end_col_letter}{end_row}",
            values=new_rows,
            value_input_option="USER_ENTERED",
        )

    return {
        "tab": tab_name,
        "appended": len(new_rows),
        "skipped_existing": skipped,
        "input": len(items),
    }
