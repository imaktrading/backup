"""run_harvest_snkrdunk - スニダン PSA10 補仕入 URL 投入 CLI (Phase 1).

Phase 1 (commit GO 2026-05-17) スコープ:
  - 対象 = 既存 iMakTCG listing (= 統合 Hight スプシ)
  - card_id pattern = OP\\d{2}-\\d{3} (ワンピース OP シリーズのみ)
  - 出力 = HIGH スプシ AC-AG 列 (補仕入 URL 1-5)
  - filter = displayShortConditionTitle == "PSA10" + status == 0 (出品中)

使い方:
    # dry-run (= スプシ書込なし、collected URL を JSON 出力)
    python run_harvest_snkrdunk.py --dry-run --max-rows 10

    # 本番投入
    python run_harvest_snkrdunk.py --max-rows 50

    # 特定行のみ (例: HIGH 行 245)
    python run_harvest_snkrdunk.py --target-row 245
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from typing import Optional

from scrapers import snkrdunk_official
from sheet_writer import COL_EBAY_ITEM_ID, COL_TITLE, HIGH_SHEET_ID, LISTINGS_GID
from sheet_writer_snkrdunk_aux import (
    get_listings_worksheet,
    insert_aux_urls_for_row,
    open_sheet_by_id,
)


def _log(msg: str) -> None:
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}")


def _select_target_rows(
    all_values: list[list[str]],
    max_rows: Optional[int] = None,
    target_row: Optional[int] = None,
) -> list[tuple[int, str, str]]:
    """対象行を選定: title から OP card_id 抽出可、かつ item ID (B 列) ありの行のみ.

    Args:
        all_values: ws.get_all_values() の戻り値 (ヘッダー行 + データ行)
        max_rows: 最大行数 (None で全件)
        target_row: 特定 1-based 行番号のみ処理 (None で全件)

    Returns: [(row_index_1based, card_id, title)] list
    """
    targets: list[tuple[int, str, str]] = []
    for idx, row in enumerate(all_values, start=1):
        if idx == 1:
            continue  # ヘッダー行 skip
        if target_row is not None and idx != target_row:
            continue
        title = (row[COL_TITLE - 1] if len(row) >= COL_TITLE else "") or ""
        item_id = (row[COL_EBAY_ITEM_ID - 1] if len(row) >= COL_EBAY_ITEM_ID else "") or ""
        title = title.strip()
        item_id = item_id.strip()
        # Phase 1: item ID あり (= 出品済) かつ title から OP card_id 抽出可
        if not item_id or not title:
            continue
        card_id = snkrdunk_official.extract_op_card_id(title)
        if not card_id:
            continue
        targets.append((idx, card_id, title))
        if max_rows is not None and len(targets) >= max_rows:
            break
    return targets


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--max-rows", type=int, default=None,
        help="最大処理行数 (default: 全件)"
    )
    ap.add_argument(
        "--target-row", type=int, default=None,
        help="特定 1-based 行番号のみ処理 (テスト用)"
    )
    ap.add_argument(
        "--dry-run", action="store_true",
        help="スプシに書かず収集結果を JSON で出力"
    )
    ap.add_argument(
        "--headless", action="store_true",
        help="Selenium を headless で起動"
    )
    args = ap.parse_args(argv)

    _log("=== スニダン PSA10 補仕入 URL 投入 開始 ===")
    _log(f"  投入先 = 統合 Hight スプシ AC-AG 列 (sheet_id={HIGH_SHEET_ID[:14]}.., gid={LISTINGS_GID})")
    _log(f"  対象範囲 = ワンピース TCG OP シリーズのみ (card_id `OP\\d{{2}}-\\d{{3}}`)")
    _log(f"  filter = PSA10 grade + status=0 (出品中)")

    # 統合 Hight スプシ全行 fetch
    _log("HIGH スプシ全行 fetch 中...")
    sh = open_sheet_by_id(HIGH_SHEET_ID)
    ws = get_listings_worksheet(sh, gid=LISTINGS_GID)
    all_values = ws.get_all_values()
    _log(f"  全行数: {len(all_values)} (ヘッダー含む)")

    targets = _select_target_rows(
        all_values,
        max_rows=args.max_rows,
        target_row=args.target_row,
    )
    _log(f"対象行 (出品済 OP card): {len(targets)} 件")
    if not targets:
        _log("対象 0 件、終了")
        return 0

    # Selenium driver 起動 (検索 + used page render 用)
    _log("Selenium driver 起動 (snkrdunk 専用 profile)...")
    driver = snkrdunk_official.create_driver(headless=args.headless)

    results = []
    total_inserted = 0
    try:
        for i, (row_idx, card_id, title) in enumerate(targets, start=1):
            _log(f"  [{i}/{len(targets)}] row={row_idx} card={card_id!r}")
            _log(f"           title: {title[:80]}")

            info = snkrdunk_official.find_psa10_urls_for_card(card_id, driver, max_results=5)
            _log(
                f"           model_id={info['model_id']!r}, "
                f"PSA10 candidates={info['psa10_count']}, "
                f"search_failed={info['search_failed']}"
            )
            for url in info["psa10_urls"]:
                _log(f"             → {url}")

            row_result = {
                "row_index": row_idx,
                "card_id": card_id,
                "title": title,
                "snkrdunk": info,
                "insertion": None,
            }

            if args.dry_run:
                results.append(row_result)
                continue

            if not info["psa10_urls"]:
                row_result["insertion"] = {"inserted": 0, "reason": "no PSA10 urls"}
                results.append(row_result)
                continue

            # 本番投入: AC-AG 列の現状取得 → 投入
            row_values = ws.row_values(row_idx)
            ins = insert_aux_urls_for_row(
                ws, row_idx, row_values, info["psa10_urls"]
            )
            _log(
                f"           AC-AG 投入: inserted={ins['inserted']}, "
                f"skipped_existing={ins['skipped_existing']}, "
                f"skipped_overflow={ins['skipped_overflow']}"
            )
            for col_letter, url in ins["plans"]:
                _log(f"             {col_letter}{row_idx} = {url}")

            row_result["insertion"] = ins
            total_inserted += ins["inserted"]
            results.append(row_result)

        _log("")
        _log("=== 完了 ===")
        if args.dry_run:
            _log(f"dry-run 結果: {len(results)} 行分の URL 候補を収集")
            json.dump(results, sys.stdout, ensure_ascii=False, indent=2)
            sys.stdout.write("\n")
        else:
            _log(f"スプシ投入合計: {total_inserted} セル ({len(results)} 行処理)")
        return 0
    finally:
        try:
            driver.quit()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
