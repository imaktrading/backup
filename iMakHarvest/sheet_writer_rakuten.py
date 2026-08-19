"""sheet_writer_rakuten - 楽天ガチャポン収集を中間スプシの `rakuten_<label>` タブに append.

2026-08-19 新設。 `sheet_writer_mercari_search.py` の楽天版。 差分は 2つ:
  - dedupe key: 楽天は `<shop>/<商品コード>` が一意 (URL の形は変わらない)
  - 列: **HQ 回答 (2026-08-19) に合わせる**

| 列 | 中身 |
|---|---|
| A | 楽天の商品URL |
| C | 日本語タイトル |
| E | `新品` |
| F | 商品価格 |
| G | 写真URL |
| H | 商品説明 (無ければ空) |
| M | 現在価格(円) 数値のみ |
| R | `カプセルトイ` |

★**N (仕入れ価格) と P (CTR) には書かない**。 本番 HIGH ではどちらも数式で、
値を貼ると列全体が壊れる (N は ARRAYFORMULA の spill、 P は countif)。
仕入れ値を本番へ渡したい時は M列を使う。
"""
from __future__ import annotations

import re

import gspread

from sheet_writer_amazon import (
    COL_CATEGORY, COL_CONDITION, COL_DESCRIPTION, COL_IMAGES, COL_PRICE,
    COL_TITLE, COL_URL, DEFAULT_COLUMN_COUNT,
)

CATEGORY = "カプセルトイ"     # R列 (HQ 確認: 表記ゆれ禁止。 ガシャポン/ガチャガチャ は別扱い)
CONDITION = "新品"
COL_CURRENT_PRICE = 13        # M: 現在価格(円) - 監視くんが使う列。 書込可

_ITEM_RE = re.compile(r"item\.rakuten\.co\.jp/([a-z0-9_-]+)/([a-z0-9_-]+)")


def dedupe_key(url: str) -> str:
    """楽天 URL から `<shop>/<商品コード>` を作る。 取れなければ正規化 URL."""
    if not url:
        return ""
    m = _ITEM_RE.search(url.strip())
    if m:
        return f"{m.group(1)}/{m.group(2)}"
    return url.strip().split("?")[0].rstrip("/").lower()


def build_tab_name(label: str) -> str:
    safe = re.sub(r"[^\w]", "_", (label or "").strip())
    safe = re.sub(r"_+", "_", safe).strip("_")
    return f"rakuten_{safe}" if safe else "rakuten_unknown"


def build_row(item: dict, column_count: int = DEFAULT_COLUMN_COUNT) -> list:
    """1 行を組み立てる (純関数). N と P は空のまま."""
    row = [""] * column_count
    price = str(item.get("price_jpy") or "").replace(",", "").strip()
    images = item.get("image_urls") or []
    image_str = images if isinstance(images, str) else "|".join(str(u) for u in images if u)

    row[COL_URL - 1] = (item.get("url") or "").strip()
    row[COL_TITLE - 1] = str(item.get("title") or "").strip()
    row[COL_CONDITION - 1] = CONDITION
    row[COL_PRICE - 1] = price
    row[COL_IMAGES - 1] = image_str
    row[COL_DESCRIPTION - 1] = str(item.get("description") or "")
    row[COL_CURRENT_PRICE - 1] = price          # M: 数値のみ
    row[COL_CATEGORY - 1] = CATEGORY            # R
    return row


def load_keys_all_tabs(sh, prefix: str = "rakuten_") -> set:
    """rakuten_* 全タブから dedupe key を集める (タブを分けても二重に入れない)."""
    keys: set = set()
    for ws in sh.worksheets():
        if not (ws.title or "").startswith(prefix):
            continue
        try:
            rows = ws.get_all_values()
        except Exception:  # noqa: BLE001
            continue
        for row in rows[1:]:
            if len(row) >= COL_URL:
                k = dedupe_key((row[COL_URL - 1] or "").strip())
                if k:
                    keys.add(k)
    return keys


def append_items(items: list[dict], label: str = "gacha",
                 column_count: int = DEFAULT_COLUMN_COUNT,
                 known_keys: set | None = None) -> dict:
    """`rakuten_<label>` タブに append (商品コード dedup).

    known_keys を渡すと タブを読み直さない (走行中に何度も書く時、
    毎回全タブを読むと Google の読取上限に当たる)。
    """
    from sheet_writer_mercari_seller import (  # noqa: PLC0415
        _col_to_letter, _create_from_template, _ensure_header,
        open_seller_staging_sheet,
    )

    tab_name = build_tab_name(label)
    if not items:
        return {"tab": tab_name, "appended": 0, "skipped_existing": 0, "input": 0}

    sh = open_seller_staging_sheet()
    try:
        ws = sh.worksheet(tab_name)
        _ensure_header(ws, sh)
    except gspread.WorksheetNotFound:
        ws = _create_from_template(sh, tab_name)

    existing: set = set(known_keys) if known_keys is not None else load_keys_all_tabs(sh)

    new_rows, skipped, seen = [], 0, set()
    for it in items:
        key = dedupe_key(it.get("url") or "")
        if not key or key in existing or key in seen:
            skipped += 1
            continue
        seen.add(key)
        new_rows.append(build_row(it, column_count))

    if not new_rows:
        return {"tab": tab_name, "appended": 0, "skipped_existing": skipped,
                "input": len(items)}

    next_row = len(ws.get_all_values()) + 1
    end = next_row + len(new_rows) - 1
    ws.update(range_name=f"A{next_row}:{_col_to_letter(column_count)}{end}",
              values=new_rows, value_input_option="USER_ENTERED")
    if known_keys is not None:
        known_keys.update(seen)
    return {"tab": tab_name, "appended": len(new_rows),
            "skipped_existing": skipped, "input": len(items)}
