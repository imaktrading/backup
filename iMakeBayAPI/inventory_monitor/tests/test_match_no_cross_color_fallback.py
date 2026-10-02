"""サイズだけの予備照合で 別の色の行に当てない (2026-10-02、EVANGELION の OFF WHITE / NAVY 混線)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import main as M  # noqa: E402


def _sheet(row, size, color):
    return {"row_index": row, "sku_id": f"s{row}", "size": size, "color": color, "ebay_qty": 1}


def test_other_color_row_is_not_used():
    sup = [{"size": "M", "in_stock": True}]
    got = M.match_supplier_skus_with_sheet(sup, [_sheet(719, "M", "NAVY")], listing_default_color="OFF WHITE")
    assert got[0]["row_index"] is None          # NAVY の行には当てない (新しい行として扱う)


def test_same_color_row_is_used():
    sup = [{"size": "M", "in_stock": True}]
    got = M.match_supplier_skus_with_sheet(sup, [_sheet(705, "M", "OFF WHITE")], listing_default_color="OFF WHITE")
    assert got[0]["row_index"] == 705


def test_colorless_old_row_still_matches_by_size():
    sup = [{"size": "M", "in_stock": True}]
    got = M.match_supplier_skus_with_sheet(sup, [_sheet(10, "M", "")], listing_default_color="BLACK")
    assert got[0]["row_index"] == 10
