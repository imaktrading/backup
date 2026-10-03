"""棚②: まだ値下げしていない物を「値下げ候補」に書く先が定義されていなかった (2026-10-03 NameError)。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
import shelf_evict as S  # noqa: E402


def test_price_down_first_path_is_defined():
    assert S.PRICE_DOWN_FIRST_PATH.endswith("price_down_before_evict.json")
