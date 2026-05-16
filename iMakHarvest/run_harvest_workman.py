"""run_harvest_workman - Workman 公式商品 harvest CLI (Phase 2 v2).

v2 仕様確定 (2026-05-16):
  - 投入先 = **★公式在庫要チェック シート1 固定** (HIGH/LOW 対象外)
  - 書込列 = B 列 (title) + F 列 (仕入元 URL) のみ
  - AJAX 呼出は Harvest 不実装 (= 出品くん責務)
  - title 取得失敗 = fail-closed skip + ログ + アラート

使い方:
    # URL 直渡し (カンマ区切り)
    python run_harvest_workman.py --urls https://workman.jp/shop/g/g2300011882014/,...

    # ファイルから (1 行 1 URL、# 始まりはコメント)
    python run_harvest_workman.py --urls-file workman_urls.txt

    # dry-run (スプシ書込せず JSON 出力)
    python run_harvest_workman.py --urls https://workman.jp/shop/g/g2300011882014/ --dry-run
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from scrapers import workman_official
from sheet_writer_workman_official import (
    OFFICIAL_GID,
    OFFICIAL_SHEET_ID,
    write_to_official_sheet,
)


def _log(msg: str) -> None:
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}")


def _load_urls(urls_arg: str | None, urls_file: str | None) -> list[str]:
    urls: list[str] = []
    if urls_arg:
        urls.extend(u.strip() for u in urls_arg.split(",") if u.strip())
    if urls_file:
        p = Path(urls_file)
        if not p.exists():
            raise FileNotFoundError(f"URL ファイルが見つかりません: {urls_file}")
        urls.extend(
            line.strip()
            for line in p.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        )
    if not urls:
        raise ValueError("--urls または --urls-file のいずれかで対象 URL を指定してください")
    return urls


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--urls", help="Workman 商品 URL カンマ区切り")
    ap.add_argument("--urls-file", help="1 行 1 URL のファイル (# 始まりはコメント)")
    ap.add_argument(
        "--rate-limit",
        type=float,
        default=workman_official.DEFAULT_RATE_LIMIT_SEC,
        help="各 fetch 間の sleep 秒 (workman 公式への礼儀)",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="スプシに書かず、収集結果を JSON で stdout 出力",
    )
    args = ap.parse_args(argv)

    urls = _load_urls(args.urls, args.urls_file)
    _log(f"workman: harvest 開始 ({len(urls)} 件)")
    _log(f"  投入先 = ★公式在庫要チェック シート1 (sheet_id={OFFICIAL_SHEET_ID[:14]}.., gid={OFFICIAL_GID})")

    def _progress(cur, total, url):
        _log(f"  [{cur}/{total}] {url}")

    items = workman_official.fetch_products(
        urls,
        rate_limit_sec=args.rate_limit,
        progress_callback=_progress,
    )
    _log(f"workman: title 取得成功 {len(items)} / {len(urls)} 件")

    if args.dry_run:
        json.dump(items, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        _log(f"dry-run: {len(items)} 件 (スプシ書込はスキップ)")
        return 0

    _log("★公式在庫要チェック シート1 投入開始...")
    result = write_to_official_sheet(items)
    _log(
        f"スプシ書込完了: appended={result['appended']}, "
        f"skipped_existing={result['skipped_existing']}, "
        f"skipped_invalid={result['skipped_invalid']}, "
        f"input={result['input']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
