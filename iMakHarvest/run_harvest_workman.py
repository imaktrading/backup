"""run_harvest_workman - ワークマン公式商品 harvest CLI.

使い方:
    # URL 直渡し (カンマ区切り)
    python run_harvest_workman.py --sheet high --urls https://workman.jp/shop/g/g2300011882014/,https://workman.jp/shop/g/g2300016710015/

    # ファイルから (1 行 1 URL)
    python run_harvest_workman.py --sheet high --urls-file workman_urls.txt

    # dry-run
    python run_harvest_workman.py --urls https://workman.jp/shop/g/g2300011882014/ --dry-run
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from scrapers import workman_official
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


def _load_urls(urls_arg: str | None, urls_file: str | None) -> list[str]:
    urls: list[str] = []
    if urls_arg:
        urls.extend(u.strip() for u in urls_arg.split(",") if u.strip())
    if urls_file:
        p = Path(urls_file)
        if not p.exists():
            raise FileNotFoundError(f"URL ファイルが見つかりません: {urls_file}")
        urls.extend(line.strip() for line in p.read_text(encoding="utf-8").splitlines() if line.strip() and not line.strip().startswith("#"))
    if not urls:
        raise ValueError("--urls または --urls-file のいずれかで対象 URL を指定してください")
    return urls


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheet", choices=["high", "low"], help="HIGH または LOW")
    ap.add_argument("--sheet-id", help="任意のスプシ ID (--sheet を上書き)")
    ap.add_argument("--gid", type=int, default=LISTINGS_GID)
    ap.add_argument("--urls", help="Workman 商品 URL カンマ区切り")
    ap.add_argument("--urls-file", help="1 行 1 URL のファイル (# 始まりはコメント)")
    ap.add_argument("--rate-limit", type=float, default=workman_official.DEFAULT_RATE_LIMIT_SEC,
                    help="各 fetch 間の sleep 秒 (workman 公式への礼儀)")
    ap.add_argument("--dry-run", action="store_true",
                    help="スプシに書かず、収集結果を JSON で stdout 出力")
    args = ap.parse_args(argv)

    urls = _load_urls(args.urls, args.urls_file)
    _log(f"workman: harvest 開始 ({len(urls)} 件)")

    def _progress(cur, total, url):
        _log(f"  [{cur}/{total}] {url}")

    items = workman_official.fetch_products(
        urls, rate_limit_sec=args.rate_limit, progress_callback=_progress,
    )
    _log(f"workman: 収集完了 {len(items)} / {len(urls)} 件")

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
