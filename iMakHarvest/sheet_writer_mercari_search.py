"""sheet_writer_mercari_search - メルカリ検索収集を中間 staging sheet の `mercari_<label>` タブに append.

2026-08-13 新設。 `sheet_writer_yodobashi.py` の姉妹版。 列構成・書込方式 (A 起点 update で
列ズレ防止) は共有し、 差分は dedupe key のみ:
  - Mercari: URL から item_id 抽出 → "m<digits>" (= 出品ごとに一意)。
"""
from __future__ import annotations

import re

import gspread

from sheet_writer_amazon import DEFAULT_COLUMN_COUNT, COL_URL, _build_row

# メルカリ item URL から item_id 抽出 (/item/m<digits>)
_MERCARI_ITEM_RE = re.compile(r"/item/(m\d+)")


def dedupe_key(url: str) -> str:
    """メルカリ URL からデデュープ用キー ("m<digits>")。 空なら ""."""
    if not url:
        return ""
    s = url.strip()
    if not s:
        return ""
    m = _MERCARI_ITEM_RE.search(s)
    if m:
        return m.group(1)
    return s.split("?")[0].split("#")[0].rstrip("/").lower()


def build_mercari_tab_name(label: str) -> str:
    safe = re.sub(r"[^\w]", "_", (label or "").strip())
    safe = re.sub(r"_+", "_", safe).strip("_")
    return f"mercari_{safe}" if safe else "mercari_unknown"


def load_keys_all_tabs(sh, prefix: str = "mercari_") -> set:
    """中間スプシの **全 mercari_* タブ** から dedupe key を集める.

    タブをゲーム毎に分けた (2026-08-18) ため、 自タブだけ見ると
    同じ出品が別タブに二重に入る。 書込前に横断で突合する。
    """
    keys: set = set()
    for ws in sh.worksheets():
        if not (ws.title or "").startswith(prefix):
            continue
        try:
            rows = ws.get_all_values()
        except Exception:  # noqa: BLE001 - 1 タブ読めなくても他は突合する
            continue
        for row in rows[1:]:
            if len(row) >= COL_URL:
                k = dedupe_key((row[COL_URL - 1] or "").strip())
                if k:
                    keys.add(k)
    return keys


def _get_or_create_tab(sh, label: str):
    from sheet_writer_mercari_seller import (  # noqa: PLC0415
        _create_from_template,
        _ensure_header,
    )

    tab_name = build_mercari_tab_name(label)
    try:
        existing = sh.worksheet(tab_name)
        _ensure_header(existing, sh)
        return existing
    except gspread.WorksheetNotFound:
        return _create_from_template(sh, tab_name)


def append_mercari_search_items(
    items: list[dict],
    label: str = "porter",
    column_count: int = DEFAULT_COLUMN_COUNT,
    cross_tab_dedupe: bool = True,
    known_keys: set | None = None,
) -> dict:
    """メルカリ検索収集を `mercari_<label>` タブに append (item_id dedup).

    items: [{url, title?, price_jpy?, condition?, image_urls?, description?, size?, color?}]
    cross_tab_dedupe: True なら 全 mercari_* タブ横断で重複を落とす (既定)
    known_keys: 呼出側が持っている既知キー。 渡すと **タブを読み直さない**
                (走行中に何度も書く時、 毎回全タブを読むと Google の読取上限に当たる。
                 2026-08-18 に 429 で走行が落ちた)。 append した分は呼出側の set に足す。
    Returns: {"tab": str, "appended": N, "skipped_existing": M, "input": K}
    """
    from sheet_writer_mercari_seller import (  # noqa: PLC0415
        _col_to_letter,
        open_seller_staging_sheet,
    )

    tab_name = build_mercari_tab_name(label)
    if not items:
        return {"tab": tab_name, "appended": 0, "skipped_existing": 0, "input": 0}

    sh = open_seller_staging_sheet()
    ws = _get_or_create_tab(sh, label)

    existing: set[str] = set()
    if known_keys is not None:
        existing = set(known_keys)
    elif cross_tab_dedupe:
        # 全 mercari_* タブ横断 (= 別ゲームのタブに同じ出品が入るのを防ぐ)
        try:
            existing = load_keys_all_tabs(sh)
        except Exception:  # noqa: BLE001
            existing = set()
    if not existing:
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
        row = _build_row(item_for_row)
        if len(row) < column_count:
            row += [""] * (column_count - len(row))
        new_rows.append(row[:column_count])

    if not new_rows:
        return {"tab": tab_name, "appended": 0,
                "skipped_existing": skipped, "input": len(items)}

    last_row = len(ws.get_all_values())
    next_row = last_row + 1
    end_col_letter = _col_to_letter(column_count)
    end_row = next_row + len(new_rows) - 1
    ws.update(
        range_name=f"A{next_row}:{end_col_letter}{end_row}",
        values=new_rows,
        value_input_option="USER_ENTERED",
    )
    if known_keys is not None:
        known_keys.update(seen_in_batch)
    return {"tab": tab_name, "appended": len(new_rows),
            "skipped_existing": skipped, "input": len(items)}
