"""gshock_to_csv.normalize_features / trim_features の回帰テスト (2026-06-13).

catalog の生 feature コード (alarms:_5, cities:_+300, casio_watches 等) が出品の
Description / C:Features に裸で出ていた件の修正。eBay 正規値に正規化し、不明は drop。

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
    import gshock_to_csv as G  # noqa: E402
    sys.argv = _saved_argv
except Exception as e:  # pragma: no cover
    pytest.skip(f"gshock_to_csv import 不能: {type(e).__name__}: {e}", allow_module_level=True)


def test_raw_codes_mapped_to_ebay_values():
    out = set(G.normalize_features("alarms:_5, bluetooth, casio_watches, cities:_+300, time_zones:_38"))
    assert "Bluetooth" in out
    assert "Alarm" in out            # alarms:_5 → Alarm (数量サフィックス除去)
    assert "World Time" in out       # cities/time_zones → World Time
    # 生コード・ノイズは消える
    assert not any(":" in v or "_" in v for v in out)
    assert "casio_watches" not in out


def test_unmappable_codes_dropped():
    out = G.normalize_features("carbon_guard_core, alphagel, screw_back, step_tracker, tide_graph")
    # どれも eBay フィルタに無い → 共通機能だけ残る
    assert "carbon_guard_core" not in out
    assert "alphagel" not in out
    assert set(out) == set(G.GSHOCK_COMMON_FEATURES)


def test_clean_values_preserved_and_corrected():
    out = set(G.normalize_features("Shock-Resistant, Solar Powered, Radio Controlled, Carbon Core Guard"))
    assert "Solar Powered" in out
    assert "Atomic/Radio Controlled" in out   # "Radio Controlled" → 正規名に矯正
    assert "Carbon Core Guard" not in out      # eBay フィルタに無い → drop


def test_common_features_always_added():
    for f in G.GSHOCK_COMMON_FEATURES:
        assert f in G.normalize_features("")          # 入力空でも共通機能は付く


def test_all_outputs_are_ebay_valid():
    out = G.normalize_features("tough_solar, multi_band_6, world_time, auto_light, alphagel, moon_graph")
    for v in out:
        assert v in G.EBAY_FEATURES_VALID            # 出力は必ず eBay 正規値

def test_trim_features_normalizes_and_limits_length():
    s = G.trim_features("alarms:_5, bluetooth, casio_watches, cities:_+300, time_zones:_38")
    assert "casio_watches" not in s and ":_" not in s
    assert len(s) <= 65
