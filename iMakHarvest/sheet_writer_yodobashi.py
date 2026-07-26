"""sheet_writer_yodobashi - ヨドバシ商品を 中間 staging sheet の `yodobashi_<label>` タブに append.

2026-07-26 新設。 `sheet_writer_amazon.py` の姉妹版。 列構成・書込方式 (A 起点 update で
列ズレ防止) は Amazon 版と完全共有し、 差分は dedupe key のみ:
  - Amazon: URL から ASIN 抽出 → "amzn:<ASIN>"
  - Yodobashi: URL から product_id 抽出 → "ydb:<product_id>" (= URL 形式差を吸収)

列 (sheet_writer_amazon と同一): A=URL / C=title / E=New / F=価格 / AI(35)=型番。
型番 (AI 列) は Amazon 側と同じ列なので、 両タブの AI 列突合で仕入元差分が取れる。
"""
from __future__ import annotations

import re

import gspread

from sheet_writer_amazon import DEFAULT_COLUMN_COUNT, COL_URL, _build_row

# ヨドバシ product URL から product_id 抽出 (/product/<digits>/)
_YDB_PID_RE = re.compile(r"/product/(\d+)(?:[/?]|$)")


def dedupe_key(url: str) -> str:
    """ヨドバシ URL からデデュープ用キーを生成 ("ydb:<product_id>")。 空なら ""."""
    if not url:
        return ""
    s = url.strip()
    if not s:
        return ""
    m = _YDB_PID_RE.search(s)
    if m:
        return f"ydb:{m.group(1)}"
    return s.split("?")[0].split("#")[0].rstrip("/").lower()


def build_yodobashi_tab_name(label: str) -> str:
    safe = re.sub(r"[^\w]", "_", (label or "").strip())
    safe = re.sub(r"_+", "_", safe).strip("_")
    return f"yodobashi_{safe}" if safe else "yodobashi_unknown"


def _get_or_create_tab(sh, label: str):
    """`yodobashi_<label>` タブ取得、 無ければ template 「商品管理シート」 複製 create."""
    from sheet_writer_mercari_seller import (  # noqa: PLC0415
        _create_from_template,
        _ensure_header,
    )

    tab_name = build_yodobashi_tab_name(label)
    try:
        existing = sh.worksheet(tab_name)
        _ensure_header(existing, sh)
        return existing
    except gspread.WorksheetNotFound:
        return _create_from_template(sh, tab_name)


def append_yodobashi_items(
    items: list[dict],
    label: str = "gshock",
    column_count: int = DEFAULT_COLUMN_COUNT,
) -> dict:
    """yodobashi 収集結果を `yodobashi_<label>` タブに append (product_id dedup).

    items: [{url, title?, price_jpy?, model_number?, ...}]
    Returns: {"tab": str, "appended": N, "skipped_existing": M, "input": K}
    """
    from sheet_writer_mercari_seller import (  # noqa: PLC0415
        _col_to_letter,
        open_seller_staging_sheet,
    )

    tab_name = build_yodobashi_tab_name(label)
    if not items:
        return {"tab": tab_name, "appended": 0, "skipped_existing": 0, "input": 0}

    sh = open_seller_staging_sheet()
    ws = _get_or_create_tab(sh, label)

    existing: set[str] = set()
    try:
        all_values = ws.get_all_values()
        if len(all_values) >= 2:
            for row in all_values[1:]:
                if len(row) >= COL_URL:
                    k = dedupe_key((row[COL_URL - 1] or "").strip())
                    if k:
                        existing.add(k)
    except Exception:
        pass

    new_rows: list[list[str]] = []
    skipped = 0
    seen_in_batch: set[str] = set()
    for it in items:
        url = (it.get("url") or "").strip()
        key = dedupe_key(url)
        if not key or key in existing or key in seen_in_batch:
            skipped += 1
            continue
        seen_in_batch.add(key)
        item_for_row = dict(it)
        item_for_row.setdefault("url", url)
        item_for_row.setdefault("condition", "New")  # ヨドバシ新品基準
        row = _build_row(item_for_row)
        if len(row) < column_count:
            row += [""] * (column_count - len(row))
        new_rows.append(row[:column_count])

    if not new_rows:
        return {"tab": tab_name, "appended": 0,
                "skipped_existing": skipped, "input": len(items)}

    # A 起点 update で列ズレ防止 (= amazon_gshock で発生した AC 列書込事故の対策と同じ)
    last_row = len(ws.get_all_values())
    next_row = last_row + 1
    end_col_letter = _col_to_letter(column_count)
    end_row = next_row + len(new_rows) - 1
    ws.update(
        range_name=f"A{next_row}:{end_col_letter}{end_row}",
        values=new_rows,
        value_input_option="USER_ENTERED",
    )
    return {"tab": tab_name, "appended": len(new_rows),
            "skipped_existing": skipped, "input": len(items)}
