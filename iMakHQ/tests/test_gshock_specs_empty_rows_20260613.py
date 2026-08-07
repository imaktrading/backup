"""gshock_to_csv.build_specs_html の回帰テスト (2026-06-13).

Description の Specifications ブロックで、値が空の項目は行ごと出さないこと。
(catalog が空欄の Movement/Display/Case Material 等が「Movement:」と裸で残る指摘の修正)

gshock_to_csv は undetected_chromedriver 等の重い import を持つため import 不能環境では skip。
"""
import os
import sys

import pytest

_GSHOCK_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "iMakG-shock"))
if _GSHOCK_DIR not in sys.path:
    sys.path.insert(0, _GSHOCK_DIR)

try:
    _saved_argv = sys.argv
    sys.argv = ["gshock_to_csv.py"]
    import gshock_to_csv  # noqa: E402
    sys.argv = _saved_argv
except Exception as e:  # pragma: no cover
    pytest.skip(f"gshock_to_csv import 不能: {type(e).__name__}: {e}", allow_module_level=True)


def test_empty_specs_rows_are_omitted():
    # Movement/Display/Case Material を空にした実データ相当 (GST-B600D-1A のケース)
    data = {
        "model_official": "GST-B600D-1A",
        "movement": "", "display": "", "case_material": "",
        "water_resistance": "200 m (20 ATM)",
        "features": "Shock Resistant",
        "case_size": "42.3 mm", "crystal": "Mineral Glass", "band_material": "Metal",
    }
    html = gshock_to_csv.build_specs_html(data)
    # 空項目は label ごと消える (裸の "Movement:" を残さない)
    assert "Movement:" not in html
    assert "Display:" not in html
    assert "Case Material:" not in html
    # 値のある項目は残る
    assert "Model:" in html and "GST-B600D-1A" in html
    assert "Water Resistance:" in html and "200 m (20 ATM)" in html
    assert "Case Size:" in html and "42.3 mm" in html


def test_whitespace_only_value_is_omitted():
    data = {"model_official": "DW-5600", "movement": "   ", "water_resistance": "200 m"}
    html = gshock_to_csv.build_specs_html(data)
    assert "Movement:" not in html
    assert "Model:" in html


def test_filled_specs_all_render():
    data = {
        "model_official": "GMW-B5000D-2", "movement": "Solar", "display": "Digital",
        "water_resistance": "200 m", "features": "Tough Solar", "crystal": "Sapphire",
        "case_material": "Stainless Steel", "band_material": "Stainless Steel",
    }
    html = gshock_to_csv.build_specs_html(data)
    for label in ("Movement:", "Display:", "Water Resistance:", "Crystal:",
                  "Case Material:", "Band Material:"):
        assert label in html
