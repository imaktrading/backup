"""backfill_color_size - スプシの指定行 S/T 列を後付けで埋める汎用ツール.

`backfill_color_size_montbell.py` の汎用版。row range or URL list で対象指定可能。
他列 (A/B/C/D/E/F/G/H, I-R) は一切触らない。

使い方:
    # HIGH スプシ rows 460-468 を backfill
    python tools/backfill_color_size.py --sheet high --rows 460-468

    # LOW スプシで個別 URL 指定
    python tools/backfill_color_size.py --sheet low --urls https://jp.mercari.com/item/m...,https://...

挙動:
  1. スプシの全行をスキャンし、対象行 (rows 範囲 or URL マッチ) の URL を取得
  2. 各 URL に Mercari 詳細ページ訪問 → color/size 取得 (TCG は自動 skip)
  3. 該当行の S/T 列だけ batch_update
  4. 既存値と新値を log で表示

エラー時:
  - 行が空 / URL 不正 → 警告 log、その行は skip
  - 商品ページ取得失敗 → 警告 log、その行は skip
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scrapers import mercari_item_detail, mercari_likes  # noqa: E402
from sheet_writer import (  # noqa: E402
    COL_COLOR,
    COL_SIZE,
    COL_URL,
    HIGH_SHEET_ID,
    LISTINGS_GID,
    LOW_SHEET_ID,
    get_listings_worksheet,
    open_sheet_by_id,
)


def _log(msg: str) -> None:
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}")


def _col_letter(col_1based: int) -> str:
    s = ""
    n = col_1based
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _parse_rows_arg(s: str) -> tuple[int, int]:
    """'460-468' → (460, 468)"""
    if "-" not in s:
        raise ValueError(f"--rows 形式は START-END (例: 460-468)、入力: {s}")
    parts = s.split("-")
    if len(parts) != 2:
        raise ValueError(f"--rows 形式不正: {s}")
    try:
        start, end = int(parts[0]), int(parts[1])
    except ValueError:
        raise ValueError(f"--rows 数値変換失敗: {s}")
    if start > end:
        raise ValueError(f"--rows: start > end ({start} > {end})")
    return start, end


def _resolve_sheet_id(sheet: str) -> str:
    if sheet == "high":
        return HIGH_SHEET_ID
    if sheet == "low":
        return LOW_SHEET_ID
    raise ValueError(f"--sheet は high/low のみ対応、入力: {sheet}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="スプシ S/T 列 (色/サイズ) の後付け補完")
    ap.add_argument("--sheet", choices=["high", "low"], required=True)
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--rows", help="行範囲 START-END (例: 460-468)")
    group.add_argument("--urls", help="URL カンマ区切り")
    args = ap.parse_args(argv)

    sheet_id = _resolve_sheet_id(args.sheet)
    _log(f"{args.sheet.upper()} スプシ open: sheet_id={sheet_id[:14]}.., gid={LISTINGS_GID}")
    sh = open_sheet_by_id(sheet_id)
    ws = get_listings_worksheet(sh, gid=LISTINGS_GID)

    _log("全行スキャン中...")
    all_values = ws.get_all_values()
    _log(f"  既存行数 (header 含む): {len(all_values)}")

    # 対象行を決定
    targets: list[tuple[int, str]] = []  # (row_idx, url)
    if args.rows:
        start, end = _parse_rows_arg(args.rows)
        _log(f"対象行範囲: {start}-{end} ({end - start + 1} 行)")
        for row_idx in range(start, end + 1):
            if row_idx > len(all_values):
                _log(f"  ⚠️ row {row_idx} は範囲外 (max {len(all_values)}), skip")
                continue
            row = all_values[row_idx - 1]
            url = (row[COL_URL - 1] if len(row) >= COL_URL else "") or ""
            url = url.strip()
            if not url:
                _log(f"  ⚠️ row {row_idx}: A 列 URL 空、skip")
                continue
            targets.append((row_idx, url))
    else:
        # --urls 指定: URL → 行検索
        url_list = [u.strip() for u in args.urls.split(",") if u.strip()]
        url_to_row: dict[str, int] = {}
        for idx, row in enumerate(all_values, start=1):
            if not row or len(row) < COL_URL:
                continue
            existing_url = (row[COL_URL - 1] or "").strip()
            if existing_url:
                url_to_row[existing_url] = idx
        for url in url_list:
            row_idx = url_to_row.get(url)
            if not row_idx:
                _log(f"  ⚠️ URL に対応する行なし: {url}")
                continue
            targets.append((row_idx, url))

    if not targets:
        _log("対象行なし、終了")
        return 0
    _log(f"処理対象: {len(targets)} 行")

    _log("Selenium driver 起動 (Mercari)...")
    driver = mercari_likes.create_driver(headless=False)

    updates: list[tuple[int, str, str, str, str]] = []
    try:
        for i, (row_idx, url) in enumerate(targets, start=1):
            existing = all_values[row_idx - 1] if row_idx - 1 < len(all_values) else []
            old_color = (existing[COL_COLOR - 1] if len(existing) >= COL_COLOR else "") or ""
            old_size = (existing[COL_SIZE - 1] if len(existing) >= COL_SIZE else "") or ""

            _log(f"  [{i}/{len(targets)}] row={row_idx} fetch: {url}")
            detail = mercari_item_detail.fetch_detail(driver, url)
            if detail is None:
                _log(f"           ❌ 詳細取得失敗 (DOM 解析不能), skip")
                continue

            new_color = detail.get("color", "") or ""
            new_size = detail.get("size", "") or ""
            _log(f"           color: {old_color!r} → {new_color!r}")
            _log(f"           size : {old_size!r} → {new_size!r}")
            updates.append((row_idx, new_color, new_size, old_color, old_size))

            time.sleep(1.0)  # rate limiting
    finally:
        try:
            driver.quit()
        except Exception:
            pass

    if not updates:
        _log("更新対象なし、終了")
        return 0

    s_col = _col_letter(COL_COLOR)  # "S"
    t_col = _col_letter(COL_SIZE)   # "T"
    batch_data = [
        {"range": f"{s_col}{row}:{t_col}{row}", "values": [[color, size]]}
        for row, color, size, _, _ in updates
    ]

    _log(f"スプシ batch_update: {len(updates)} 行 ({s_col}/{t_col} 列のみ)")
    ws.batch_update(batch_data, value_input_option="USER_ENTERED")
    _log(f"✅ 完了: {len(updates)} 行更新")

    _log("")
    _log("=== 更新結果 ===")
    for row, color, size, old_color, old_size in updates:
        _log(f"  row {row}: S={color!r} (was {old_color!r}), T={size!r} (was {old_size!r})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
