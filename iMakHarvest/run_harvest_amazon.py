"""run_harvest_amazon - Amazon ウィッシュリスト URL 収集 → スプシ書込のエントリポイント.

`run_harvest.py` (Mercari 用) の Amazon 版コピー。
Mercari 用 run_harvest.py は一切 import せず独立。

使い方:
    # 収集 + HIGH スプシに書込
    python run_harvest_amazon.py \\
        --wishlist-url "https://www.amazon.co.jp/hz/wishlist/ls/10T7E6IA1HL9" \\
        --sheet high

    # 任意スプシに書込
    python run_harvest_amazon.py \\
        --wishlist-url <URL> \\
        --sheet-id <SHEET_ID>

    # ドライラン (収集結果を JSON 出力)
    python run_harvest_amazon.py --wishlist-url <URL> --dry-run
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime

from scrapers import amazon_wishlist
from sheet_writer_amazon import (
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


def harvest_amazon(
    wishlist_url: str,
    max_items: int,
    load_more_clicks: int,
    headless: bool,
    fetch_detail: bool = True,
    exclude_unavailable: bool = True,
) -> list[dict]:
    """Amazon ウィッシュリスト収集. 失敗時は raise."""
    _log(f"amazon: ウィッシュリスト収集開始 "
         f"(max={max_items}, load_more={load_more_clicks}, "
         f"headless={headless}, fetch_detail={fetch_detail}, "
         f"exclude_unavailable={exclude_unavailable})")
    if fetch_detail:
        def _progress(cur, total, msg):
            _log(f"  [{cur}/{total}] {msg}")
        items = amazon_wishlist.collect_wishlist_with_details(
            wishlist_url=wishlist_url,
            max_items=max_items,
            load_more_clicks=load_more_clicks,
            headless=headless,
            exclude_unavailable=exclude_unavailable,
            progress_callback=_progress,
        )
    else:
        items = amazon_wishlist.collect_wishlist_urls(
            wishlist_url=wishlist_url,
            max_items=max_items,
            load_more_clicks=load_more_clicks,
            headless=headless,
        )
    _log(f"amazon: 収集完了 {len(items)} 件")
    return items


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--wishlist-url",
        required=True,
        help="公開ウィッシュリスト URL (https://www.amazon.co.jp/hz/wishlist/ls/...)",
    )
    ap.add_argument("--sheet", choices=["high", "low"], help="HIGH または LOW")
    ap.add_argument("--sheet-id", help="任意のスプシ ID (--sheet を上書き)")
    ap.add_argument("--gid", type=int, default=LISTINGS_GID, help="ワークシート gid")
    ap.add_argument("--max-items", type=int, default=amazon_wishlist.DEFAULT_MAX_ITEMS)
    ap.add_argument("--load-more", type=int, default=amazon_wishlist.DEFAULT_LOAD_MORE_CLICKS)
    ap.add_argument("--headless", action="store_true", help="Chrome を headless で起動")
    ap.add_argument(
        "--no-detail",
        action="store_true",
        help="商品詳細 (タイトル/価格/画像/説明) を取得しない (URL のみ高速モード)",
    )
    ap.add_argument(
        "--include-unavailable",
        action="store_true",
        help="在庫切れ・取扱中止商品も含める (default: 除外)",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="スプシに書かず、収集結果を JSON で stdout に出力",
    )
    args = ap.parse_args(argv)

    items = harvest_amazon(
        wishlist_url=args.wishlist_url,
        max_items=args.max_items,
        load_more_clicks=args.load_more,
        headless=args.headless,
        fetch_detail=not args.no_detail,
        exclude_unavailable=not args.include_unavailable,
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
