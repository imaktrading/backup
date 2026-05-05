"""run_harvest_mercari_shops - Mercari Shops いいね収集 → スプシ書込のエントリポイント.

`run_harvest.py` (Mercari 通常品) の Shops 版コピー。Mercari 通常品 CLI は touch なし。

使い方:
    # 収集 + HIGH スプシに書込
    python run_harvest_mercari_shops.py --sheet high

    # 任意スプシに書込
    python run_harvest_mercari_shops.py --sheet-id <SHEET_ID>

    # ドライラン
    python run_harvest_mercari_shops.py --sheet high --dry-run
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime

from scrapers import mercari_shops_likes
from sheet_writer import (
    HIGH_SHEET_ID,
    LISTINGS_GID,
    LOW_SHEET_ID,
    write_to_sheet,
)


def _log(msg: str) -> None:
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}")


def resolve_sheet_id(sheet: str | None, sheet_id: str | None) -> str:
    if sheet_id:
        return sheet_id
    if sheet == "high":
        return HIGH_SHEET_ID
    if sheet == "low":
        return LOW_SHEET_ID
    raise ValueError("--sheet (high/low) または --sheet-id を指定してください")


def harvest_mercari_shops(
    max_items: int,
    load_more_clicks: int,
    headless: bool,
    fetch_detail: bool = True,
    exclude_sold: bool = True,
) -> list[dict]:
    """Mercari Shops いいね収集. 失敗時は raise."""
    _log(f"mercari_shops: いいね収集開始 (max={max_items}, load_more={load_more_clicks}, "
         f"headless={headless}, fetch_detail={fetch_detail}, exclude_sold={exclude_sold})")
    if fetch_detail:
        def _progress(cur, total, msg):
            _log(f"  [{cur}/{total}] {msg}")
        items = mercari_shops_likes.collect_shops_likes_with_details(
            max_items=max_items,
            load_more_clicks=load_more_clicks,
            headless=headless,
            exclude_sold=exclude_sold,
            progress_callback=_progress,
        )
    else:
        items = mercari_shops_likes.collect_shops_liked_urls(
            max_items=max_items,
            load_more_clicks=load_more_clicks,
            headless=headless,
        )
    _log(f"mercari_shops: 収集完了 {len(items)} 件")
    return items


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheet", choices=["high", "low"], help="HIGH または LOW")
    ap.add_argument("--sheet-id", help="任意のスプシ ID (--sheet を上書き)")
    ap.add_argument("--gid", type=int, default=LISTINGS_GID, help="ワークシート gid")
    ap.add_argument("--max-items", type=int, default=mercari_shops_likes.DEFAULT_MAX_ITEMS)
    ap.add_argument("--load-more", type=int, default=mercari_shops_likes.DEFAULT_LOAD_MORE_CLICKS)
    ap.add_argument("--headless", action="store_true")
    ap.add_argument(
        "--no-detail",
        action="store_true",
        help="商品詳細を取得しない (URL のみ高速モード)",
    )
    ap.add_argument(
        "--include-sold",
        action="store_true",
        help="SOLD 商品も含める (default: SOLD は除外)",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="スプシに書かず、収集結果を JSON で stdout に出力",
    )
    args = ap.parse_args(argv)

    items = harvest_mercari_shops(
        max_items=args.max_items,
        load_more_clicks=args.load_more,
        headless=args.headless,
        fetch_detail=not args.no_detail,
        exclude_sold=not args.include_sold,
    )

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
