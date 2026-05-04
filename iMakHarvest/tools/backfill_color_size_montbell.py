"""backfill_color_size_montbell - HIGH 行 477-482 (montbell 6 件) の S/T 列を後付けで埋める.

one-off スクリプト。Harvest は通常 append-only で既存行を更新しないが、
このスクリプトは指定した URL に対応する既存行を探して **S 列 (色) / T 列 (サイズ) のみ**
を更新する。他の列 (A/B/C/D/E/F/G/H, I-R) は一切触らない。

使い方:
    python tools/backfill_color_size_montbell.py

挙動:
  1. HIGH スプシの全行を読み込み、A 列 URL でインデックス
  2. 6 URL 各々について Mercari 詳細ページを訪問 → color/size 取得
  3. 該当行の S/T 列だけ batch_update (1 API call で全 12 セル更新)
  4. 既存値と新値を log で表示

エラー時:
  - URL が見つからない → 警告ログ、その行はスキップ
  - 商品ページ取得失敗 → 警告ログ、その行はスキップ
  - 他のエラーは raise
"""
from __future__ import annotations

import sys
import time
from datetime import datetime

# 親ディレクトリ (iMakHarvest/) を sys.path に追加
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

from scrapers import mercari_item_detail, mercari_likes  # noqa: E402
from sheet_writer import (  # noqa: E402
    COL_COLOR,
    COL_SIZE,
    COL_URL,
    HIGH_SHEET_ID,
    LISTINGS_GID,
    get_listings_worksheet,
    open_sheet_by_id,
)


URLS = [
    "https://jp.mercari.com/item/m66875521479",
    "https://jp.mercari.com/item/m54579705767",
    "https://jp.mercari.com/item/m44951860368",
    "https://jp.mercari.com/item/m68368072419",
    "https://jp.mercari.com/item/m61283250799",
    "https://jp.mercari.com/item/m71911781949",
]


def _log(msg: str) -> None:
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}")


def _col_letter(col_1based: int) -> str:
    """1-based 列番号 → A1 形式の文字 (1=A, 19=S, 20=T)."""
    s = ""
    n = col_1based
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _build_url_to_row_map(ws) -> dict[str, int]:
    """A 列の URL → 行番号 (1-based) の dict を構築."""
    all_values = ws.get_all_values()
    url_to_row: dict[str, int] = {}
    for idx, row in enumerate(all_values, start=1):
        if not row or len(row) < COL_URL:
            continue
        url = (row[COL_URL - 1] or "").strip()
        if url and url not in url_to_row:
            url_to_row[url] = idx
    return url_to_row


def main() -> int:
    _log(f"HIGH スプシ open: sheet_id={HIGH_SHEET_ID[:14]}.., gid={LISTINGS_GID}")
    sh = open_sheet_by_id(HIGH_SHEET_ID)
    ws = get_listings_worksheet(sh, gid=LISTINGS_GID)

    _log("全行スキャン中...")
    url_to_row = _build_url_to_row_map(ws)
    _log(f"  既存行数 (A 列に URL あり): {len(url_to_row)}")

    # 行番号と既存 S/T 値も取得しておく (差分表示用)
    all_values = ws.get_all_values()

    _log("Selenium driver 起動 (Mercari)...")
    driver = mercari_likes.create_driver(headless=False)

    updates: list[tuple[int, str, str, str, str]] = []
    # (row, new_color, new_size, old_color, old_size)

    try:
        for i, url in enumerate(URLS, start=1):
            row_idx = url_to_row.get(url)
            if not row_idx:
                _log(f"  [{i}/{len(URLS)}] ⚠️ 行が見つかりません: {url}")
                continue

            existing = all_values[row_idx - 1] if row_idx - 1 < len(all_values) else []
            old_color = (existing[COL_COLOR - 1] if len(existing) >= COL_COLOR else "") or ""
            old_size = (existing[COL_SIZE - 1] if len(existing) >= COL_SIZE else "") or ""

            _log(f"  [{i}/{len(URLS)}] row={row_idx} fetch: {url}")
            detail = mercari_item_detail.fetch_detail(driver, url)
            if detail is None:
                _log(f"           ❌ 詳細取得失敗 (DOM 解析不能), スキップ")
                continue

            new_color = detail.get("color", "") or ""
            new_size = detail.get("size", "") or ""
            _log(f"           color: {old_color!r} → {new_color!r}")
            _log(f"           size : {old_size!r} → {new_size!r}")
            updates.append((row_idx, new_color, new_size, old_color, old_size))

            # rate limiting (Mercari への礼儀 + AI API への暴走防止)
            time.sleep(1.0)
    finally:
        try:
            driver.quit()
        except Exception:
            pass

    if not updates:
        _log("更新対象なし、終了")
        return 0

    # batch_update で S/T 列を一括更新 (1 API call)
    s_col = _col_letter(COL_COLOR)  # "S"
    t_col = _col_letter(COL_SIZE)   # "T"
    batch_data = [
        {
            "range": f"{s_col}{row}:{t_col}{row}",
            "values": [[color, size]],
        }
        for row, color, size, _, _ in updates
    ]

    _log(f"スプシ batch_update: {len(updates)} 行 ({s_col}/{t_col} 列のみ)")
    ws.batch_update(batch_data, value_input_option="USER_ENTERED")
    _log(f"✅ 完了: {len(updates)} 行更新")

    # サマリ
    _log("")
    _log("=== 更新結果 ===")
    for row, color, size, old_color, old_size in updates:
        _log(f"  row {row}: S={color!r} (was {old_color!r}), T={size!r} (was {old_size!r})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
