"""run_harvest - URL 収集 → スプシ書込のエントリポイント.

使い方 (Phase 1a):
    # 初回ログイン
    python -m scrapers.mercari_likes --login

    # 収集 + HIGH スプシに書込
    python run_harvest.py --supplier mercari --sheet high

    # 収集 + LOW スプシに書込
    python run_harvest.py --supplier mercari --sheet low

    # 任意スプシに書込
    python run_harvest.py --supplier mercari --sheet-id <SHEET_ID>

    # ドライラン (スプシに書かず収集結果を出力)
    python run_harvest.py --supplier mercari --dry-run

NG (CLAUDE.md 規約):
  - 既存スプシ行を上書きしない (write_to_sheet が append_rows のみ呼ぶことで担保)
  - item_id 単位デドゥープ必須 (sheet_writer.append_new_urls 内で実装)
  - iMakInventory への副作用なし (本ファイルから iMakInventory コードを import しない)
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime

from scrapers import mercari_likes
from sheet_writer import (
    HIGH_SHEET_ID,
    LISTINGS_GID,
    LOW_SHEET_ID,
    write_to_sheet,
)


def _log(msg: str) -> None:
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}")


def resolve_sheet_id(sheet: str | None, sheet_id: str | None) -> str:
    """--sheet (high/low) または --sheet-id から spreadsheet ID を解決."""
    if sheet_id:
        return sheet_id
    if sheet == "high":
        return HIGH_SHEET_ID
    if sheet == "low":
        return LOW_SHEET_ID
    raise ValueError("--sheet (high/low) または --sheet-id を指定してください")


def harvest_mercari(
    max_items: int,
    load_more_clicks: int,
    headless: bool,
) -> list[dict]:
    """Mercari いいね収集. 失敗時は raise."""
    _log(f"mercari: いいね収集開始 (max={max_items}, load_more={load_more_clicks}, headless={headless})")
    items = mercari_likes.collect_liked_urls(
        max_items=max_items,
        load_more_clicks=load_more_clicks,
        headless=headless,
    )
    _log(f"mercari: 収集完了 {len(items)} 件")
    return items


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--supplier",
        choices=["mercari"],
        required=True,
        help="収集対象 (Phase 1a は mercari のみ)",
    )
    ap.add_argument("--sheet", choices=["high", "low"], help="HIGH または LOW")
    ap.add_argument("--sheet-id", help="任意のスプシ ID (--sheet を上書き)")
    ap.add_argument("--gid", type=int, default=LISTINGS_GID, help="ワークシート gid")
    ap.add_argument("--max-items", type=int, default=mercari_likes.DEFAULT_MAX_ITEMS)
    ap.add_argument("--load-more", type=int, default=mercari_likes.DEFAULT_LOAD_MORE_CLICKS)
    ap.add_argument("--headless", action="store_true", help="Chrome を headless で起動")
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="スプシに書かず、収集結果を JSON で stdout に出力",
    )
    args = ap.parse_args(argv)

    if args.supplier == "mercari":
        items = harvest_mercari(
            max_items=args.max_items,
            load_more_clicks=args.load_more,
            headless=args.headless,
        )
    else:
        raise NotImplementedError(args.supplier)

    if args.dry_run:
        json.dump(items, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        _log(f"dry-run: {len(items)} 件 (スプシ書込はスキップ)")
        return 0

    sheet_id = resolve_sheet_id(args.sheet, args.sheet_id)
    _log(f"スプシ書込開始: sheet_id={sheet_id} gid={args.gid}")
    result = write_to_sheet(items, spreadsheet_id=sheet_id, gid=args.gid)
    _log(f"スプシ書込完了: {result}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
