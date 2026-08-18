"""fix_image_url_column - G列 (写真URL) が 1文字ずつ "|" で割れた行を直す.

2026-08-18: 移送ツール `split_psa10_by_game.py` が スプシのセル (str) を
`image_urls` に渡し、 `_build_row` が 1 文字ずつ join した
("https://..." → "h|t|t|p|s|:|/|/|..."）。

復元は s[::2] でよい (1文字おきに "|" が挟まった形なので、 元の文字列がそのまま戻る。
元 URL 区切りの "|" 自体も その位置に残っている)。

使い方:
  python tools/fix_image_url_column.py --dry-run
  python tools/fix_image_url_column.py
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sheet_writer_amazon import COL_IMAGES  # noqa: E402


def _log(m: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


def is_broken(value: str) -> bool:
    """1文字ずつ "|" で割れているか。 直せる形かどうかまで見る (fail-closed)."""
    s = value or ""
    if not s or s.startswith("http"):
        return False
    return len(s) > 3 and s[1] == "|" and s[::2].startswith("http")


def repair(value: str) -> str:
    return (value or "")[::2]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prefix", default="mercari_", help="対象タブの接頭辞")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    from sheet_writer_mercari_seller import open_seller_staging_sheet  # noqa: PLC0415

    sh = open_seller_staging_sheet()
    total = 0
    for ws in sh.worksheets():
        if not (ws.title or "").startswith(args.prefix):
            continue
        values = ws.get_all_values()
        updates = []
        for i, row in enumerate(values[1:], start=2):
            cur = row[COL_IMAGES - 1] if len(row) >= COL_IMAGES else ""
            if is_broken(cur):
                updates.append({"range": f"G{i}", "values": [[repair(cur)]]})
        if not updates:
            continue
        total += len(updates)
        _log(f"{ws.title}: 壊れている行 {len(updates)}")
        if not args.dry_run:
            ws.batch_update(updates, value_input_option="USER_ENTERED")
            _log(f"  → {len(updates)} 行を修復")
    _log(f"合計 {total} 行" + (" (dry-run → 書込なし)" if args.dry_run else " を修復"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
