"""ebay_rate_limits.reset_to_jst() の UTC→JST 変換テスト (2026-06-04)。純関数・ネットワーク非依存。"""
import importlib.util
import os

_SPEC = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "iMakHQ", "tools", "ebay_rate_limits.py"))
_spec = importlib.util.spec_from_file_location("ebay_rate_limits", _SPEC)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


def test_utc_to_jst_offset():
    """07:00 UTC は 16:00 JST (+9h)。日付・時刻部分を検証。"""
    s = mod.reset_to_jst("2026-06-04T07:00:00.000Z")
    assert "06-04 16:00 JST" in s


def test_empty_reset():
    assert mod.reset_to_jst("") == "?"
    assert mod.reset_to_jst(None) == "?"


def test_midnight_utc_crosses_date():
    """00:00 UTC は同日 09:00 JST。"""
    assert "09:00 JST" in mod.reset_to_jst("2026-06-04T00:00:00.000Z")
