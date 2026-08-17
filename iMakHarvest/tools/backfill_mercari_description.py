"""backfill_mercari_description - 中間スプシ `mercari_<label>` の H列 (商品説明) 空欄を埋め直す.

2026-08-17 新設。 2026-08-15 のポーター走行で 56行の H列が空欄のまま入っていた
(詳細フェッチ時に description が取れず、 空文字が silent に書かれた) ため、
URL から再フェッチして H列だけを更新する。

使い方:
  python tools/backfill_mercari_description.py --label porter --dry-run
  python tools/backfill_mercari_description.py --label porter
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sheet_writer_amazon import COL_DESCRIPTION, COL_URL  # noqa: E402
from scrapers import mercari_item_detail  # noqa: E402
from scrapers import mercari_seller as MS  # noqa: E402


def _log(m: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="porter", help="対象タブ (= mercari_<label>)")
    ap.add_argument("--headless", action="store_true", default=True)
    ap.add_argument("--no-headless", dest="headless", action="store_false")
    ap.add_argument("--limit", type=int, default=0, help="処理上限 (0=無制限)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    from sheet_writer_mercari_search import build_mercari_tab_name  # noqa: PLC0415
    from sheet_writer_mercari_seller import open_seller_staging_sheet  # noqa: PLC0415

    tab = build_mercari_tab_name(args.label)
    sh = open_seller_staging_sheet()
    ws = sh.worksheet(tab)
    values = ws.get_all_values()

    targets: list[tuple[int, str]] = []  # (1-based row, url)
    for i, row in enumerate(values[1:], start=2):
        url = (row[COL_URL - 1] if len(row) >= COL_URL else "").strip()
        desc = (row[COL_DESCRIPTION - 1] if len(row) >= COL_DESCRIPTION else "").strip()
        if url and not desc:
            targets.append((i, url))
    if args.limit:
        targets = targets[:args.limit]

    _log(f"{tab}: 全{len(values) - 1}行 / H列空欄 {len(targets)}行")
    if not targets:
        return 0
    if args.dry_run:
        for r, u in targets[:5]:
            _log(f"  (dry) row{r} {u}")
        _log("dry-run → 書込なし")
        return 0

    driver = MS.create_anonymous_driver(headless=args.headless)
    updates: list[dict] = []
    empty: list[tuple[int, str]] = []  # 再フェッチしても取れなかった行 (= 要対応)
    try:
        for n, (row_i, url) in enumerate(targets, 1):
            try:
                detail = mercari_item_detail.fetch_detail(driver, url)
            except Exception as e:  # noqa: BLE001
                _log(f"  row{row_i} fetch 例外: {type(e).__name__}")
                empty.append((row_i, url))
                continue
            desc = ((detail or {}).get("description") or "").strip()
            if desc:
                updates.append({"range": f"H{row_i}", "values": [[desc]]})
            else:
                status = (detail or {}).get("status") if detail else "FETCH_FAIL"
                empty.append((row_i, url))
                _log(f"  row{row_i} 説明取れず (status={status})")
            if n % 10 == 0 or n == len(targets):
                _log(f"  {n}/{len(targets)} (取得 {len(updates)} / 空 {len(empty)})")
            time.sleep(1.0)
    finally:
        try:
            driver.quit()
        except Exception:
            pass

    if updates:
        ws.batch_update(updates, value_input_option="USER_ENTERED")
    _log(f"完了: H列 更新 {len(updates)}行 / 取れず {len(empty)}行")
    if empty:
        _log("⚠️要対応 (説明が取れなかった行):")
        for r, u in empty:
            _log(f"    row{r} {u}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
