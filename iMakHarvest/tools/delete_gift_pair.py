"""中間スプシ amazon_gshock から ギフトセット/ペアウォッチ 行を物理削除 (= 単品本体維持).

2026-07-26 user 指示: メンズ抽出に混入した ギフトセット (バンドル SKU) と
ペアウォッチ (2 型番同梱) を削除し 単品本体のみに戻す。
判定は scrapers.amazon_search_http.is_gift_or_pair_set (= keep gate と同一基準、 単一ソース)。

実行:
  python tools/delete_gift_pair.py --dry-run
  python tools/delete_gift_pair.py
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scrapers.amazon_search_http import is_gift_or_pair_set  # noqa: E402
from sheet_writer_mercari_seller import open_seller_staging_sheet  # noqa: E402

TAB_NAME = "amazon_gshock"
COL_URL = 1
COL_TITLE = 3
COL_KEY = 35


def _cell(row, c):
    return (row[c - 1].strip() if len(row) >= c else "")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    sh = open_seller_staging_sheet()
    ws = sh.worksheet(TAB_NAME)
    vals = ws.get_all_values()

    targets = []
    for i, row in enumerate(vals[1:], start=2):
        if not row or not _cell(row, COL_URL):
            continue
        title = _cell(row, COL_TITLE)
        if is_gift_or_pair_set(title):
            targets.append({"row": i, "key": _cell(row, COL_KEY), "title": title[:50]})

    rows_desc = sorted({t["row"] for t in targets}, reverse=True)
    print(f"[delete-gift-pair] 削除対象: {len(rows_desc)} 行 (dry_run={args.dry_run})", flush=True)
    for t in sorted(targets, key=lambda x: x["row"]):
        print(f"  row{t['row']} KEY={t['key']!r} | {t['title']}", flush=True)

    deleted = 0
    if rows_desc and not args.dry_run:
        for r in rows_desc:
            try:
                ws.delete_rows(r)
                deleted += 1
                time.sleep(0.6)
            except Exception as e:
                print(f"  WARN delete row {r}: {e!r}", flush=True)
    print(f"[delete-gift-pair] deleted={deleted}", flush=True)

    (ROOT / "debug" / "delete_gift_pair_result.json").write_text(
        json.dumps({"dry_run": args.dry_run, "targets": targets, "deleted": deleted},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
