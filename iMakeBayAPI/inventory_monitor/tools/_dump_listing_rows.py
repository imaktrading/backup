"""Dump SKU sheet rows for one listing (verification helper).

Usage:  python _dump_listing_rows.py <listing_id>
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

from sheet_updater import open_sheet, read_sku_rows  # noqa: E402


def main():
    listing_id = sys.argv[1] if len(sys.argv) > 1 else ""
    if not listing_id:
        print("Usage: python _dump_listing_rows.py <listing_id>")
        sys.exit(1)
    sh = open_sheet()
    rows = read_sku_rows(sh)
    matched = []
    for idx, r in enumerate(rows, start=2):
        r = list(r) + [""] * max(0, 15 - len(r))
        if (r[3] or "").strip() == listing_id:
            matched.append((idx, r))
    print(f"listing_id={listing_id}: {len(matched)} rows")
    header = ["row", "D listing", "F sku_id", "G size", "H color",
              "I stock", "J supplier_price", "K ebay_qty", "L auto_chk",
              "U list_price"]
    print("\t".join(header))
    for idx, r in matched:
        # cols: A=0..O=14, but U is column 21 → 需要 21 columns
        r2 = r + [""] * max(0, 21 - len(r))
        print("\t".join([
            str(idx),
            r2[3], r2[5], r2[6], r2[7],
            r2[8], r2[9], r2[10], r2[11],
            r2[20],  # U column (0-indexed 20)
        ]))


if __name__ == "__main__":
    main()
