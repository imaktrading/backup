"""graniph の色コード "001" がスプシで 1 になっても同じ行に当たること (2026-10-04 行増殖)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main as M  # noqa: E402


def _sup(size):
    return {"size": size, "color_code": "001", "in_stock": True, "quantity": 5, "price_jpy": 5340}


def test_zero_padded_code_matches_sheet_number():
    sheet = [{"row_index": 1054, "size": "SS", "color": "1", "sku_id": "c1b3", "ebay_qty": 1}]
    m = M.match_supplier_skus_with_sheet([_sup("SS")], sheet)
    assert m[0]["row_index"] == 1054


def test_other_codes_unchanged():
    assert M._normalize_color("off white") == "OFFWHITE"
    assert M._normalize_color("GP/OC") == "GP/OC"
    assert M._normalize_color("010") == "10"
    assert M._normalize_color("") == ""


def test_different_number_does_not_match():
    sheet = [{"row_index": 9, "size": "SS", "color": "2", "sku_id": "x", "ebay_qty": 1}]
    assert M.match_supplier_skus_with_sheet([_sup("SS")], sheet)[0]["row_index"] is None
