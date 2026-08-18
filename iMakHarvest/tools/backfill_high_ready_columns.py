"""backfill_high_ready_columns - 中間スプシの N (仕入れ価格) / R (カテゴリ) を埋める.

2026-08-18: 行ごとコピーで本番 (HIGH) に載せるため、 収集側で N/R を書くようにしたが、
それ以前に集めた行は空欄のまま。 F (商品価格) から N を、 R は "TCG" を入れる。
P (CTR) は HIGH 側が countif の数式なので**触らない**。

使い方:
  python tools/backfill_high_ready_columns.py            # dry-run
  python tools/backfill_high_ready_columns.py --apply
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sheet_writer_amazon import (  # noqa: E402
    COL_CATEGORY, COL_PRICE, COL_PURCHASE_PRICE,
)

CATEGORY = "TCG"


def _log(m: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prefix", default="mercari_psa10")
    ap.add_argument("--apply", action="store_true")
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
            def _cell(col):
                return (row[col - 1] or "").strip() if len(row) >= col else ""

            price = _cell(COL_PRICE).replace(",", "")
            if price and not _cell(COL_PURCHASE_PRICE):
                updates.append({"range": f"N{i}", "values": [[price]]})
            if not _cell(COL_CATEGORY):
                updates.append({"range": f"R{i}", "values": [[CATEGORY]]})
        if not updates:
            continue
        total += len(updates)
        _log(f"{ws.title}: 埋めるセル {len(updates)} (全 {len(values) - 1} 行)")
        if args.apply:
            ws.batch_update(updates, value_input_option="USER_ENTERED")
            _log("  → 書込完了")
    _log(f"合計 {total} セル" + ("" if args.apply else " (dry-run。 書くには --apply)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
