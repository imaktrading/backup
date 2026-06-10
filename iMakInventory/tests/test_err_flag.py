"""巡回ERR FLG marker (err_flag.py) の offline テスト.

連続エラー回数のインクリメント / 成功 clear / 持続判定 / 短縮型名抽出 を検証。
"""
from datetime import datetime

import pytest

import err_flag
from err_flag import (
    build_err_marker,
    marker_count,
    is_persistent,
    _short_err_type,
    PERSISTENT_THRESHOLD,
)

pytestmark = pytest.mark.offline

_NOW = datetime(2026, 6, 11, 6, 3)


def test_first_error_count_is_1():
    m = build_err_marker("ReadTimeoutError: HTTPConnectionPool(...)", "", now=_NOW)
    assert marker_count(m) == 1
    assert m == "⚠ ReadTimeout ×1 06/11 06:03"


def test_consecutive_increments_from_prev_marker():
    m1 = build_err_marker("ReadTimeoutError: x", "", now=_NOW)
    m2 = build_err_marker("ReadTimeoutError: x", m1, now=_NOW)
    m3 = build_err_marker("ReadTimeoutError: x", m2, now=_NOW)
    assert marker_count(m1) == 1
    assert marker_count(m2) == 2
    assert marker_count(m3) == 3


def test_count_resets_when_prev_empty():
    # 成功して clear ("") された後に再エラー → 1 から再カウント
    m = build_err_marker("Timeout", "", now=_NOW)
    assert marker_count(m) == 1


def test_marker_count_of_blank_is_0():
    assert marker_count("") == 0
    assert marker_count(None) == 0
    assert marker_count("巡回ERR") == 0  # ヘッダ等 ×N 無し


def test_is_persistent_threshold():
    m2 = build_err_marker("E", build_err_marker("E", "", now=_NOW), now=_NOW)  # ×2
    m3 = build_err_marker("E", m2, now=_NOW)  # ×3
    assert not is_persistent(m2)
    assert is_persistent(m3)
    assert PERSISTENT_THRESHOLD == 3


@pytest.mark.parametrize("err,expected", [
    ("ReadTimeoutError: HTTPConnectionPool(...)", "ReadTimeout"),
    ("unsupported supplier: foo (bar.com)", "unsupported"),
    ("scraper returned None (fail-closed)", "scraper"),
    ("in_stock indeterminate (...)", "in_stock"),
    ("", "Error"),
    ("ValueError", "Value"),
])
def test_short_err_type(err, expected):
    assert _short_err_type(err) == expected


def test_marker_format_is_parseable_roundtrip():
    # 別エラー型でも count は prev marker から正しく継承される (型が変わっても回数は累積)
    prev = build_err_marker("ReadTimeoutError: x", "", now=_NOW)        # ×1
    nxt = build_err_marker("ConnectionError: y", prev, now=_NOW)        # ×2 (型は別)
    assert marker_count(nxt) == 2
    assert "Connection" in nxt


def test_both_codebases_marker_format_identical():
    # 公式側 err_flag と HIGH/LOW 側 err_flag の marker format が一致していること
    import importlib.util
    import pathlib
    official = pathlib.Path(err_flag.__file__).resolve().parents[1] / \
        "iMakeBayAPI" / "inventory_monitor" / "err_flag.py"
    spec = importlib.util.spec_from_file_location("err_flag_official", official)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    a = build_err_marker("ReadTimeoutError: x", "", now=_NOW)
    b = mod.build_err_marker("ReadTimeoutError: x", "", now=_NOW)
    assert a == b
    assert mod.PERSISTENT_THRESHOLD == PERSISTENT_THRESHOLD
