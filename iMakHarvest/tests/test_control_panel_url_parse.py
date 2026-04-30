"""tests/test_control_panel_url_parse - parse_sheet_url の単体テスト.

Tkinter UI 部分はテストしない (環境依存)。URL パース関数だけ検証。
"""
from __future__ import annotations

import pytest

from control_panel import parse_sheet_url
from sheet_writer import LISTINGS_GID


pytestmark = pytest.mark.offline


class TestParseSheetUrl:
    def test_full_url_with_hash_gid(self):
        url = "https://docs.google.com/spreadsheets/d/19kj8NqWHIGP1ptQDeGePw077hpdl6dNOO-v2J10HCjk/edit#gid=851100680"
        sid, gid = parse_sheet_url(url)
        assert sid == "19kj8NqWHIGP1ptQDeGePw077hpdl6dNOO-v2J10HCjk"
        assert gid == 851100680

    def test_full_url_with_query_gid(self):
        url = "https://docs.google.com/spreadsheets/d/abc123_xyz-DEF/edit?gid=42"
        sid, gid = parse_sheet_url(url)
        assert sid == "abc123_xyz-DEF"
        assert gid == 42

    def test_full_url_with_amp_gid(self):
        url = "https://docs.google.com/spreadsheets/d/abc123_xyz-DEF/edit?usp=sharing&gid=99"
        sid, gid = parse_sheet_url(url)
        assert sid == "abc123_xyz-DEF"
        assert gid == 99

    def test_url_without_gid_falls_back_to_listings_gid(self):
        url = "https://docs.google.com/spreadsheets/d/abc123_xyz-DEF/edit"
        sid, gid = parse_sheet_url(url)
        assert sid == "abc123_xyz-DEF"
        assert gid == LISTINGS_GID

    def test_raw_sheet_id_accepted(self):
        # 生 ID (gid 無し) はそのまま受け取る
        sid, gid = parse_sheet_url("19kj8NqWHIGP1ptQDeGePw077hpdl6dNOO-v2J10HCjk")
        assert sid == "19kj8NqWHIGP1ptQDeGePw077hpdl6dNOO-v2J10HCjk"
        assert gid == LISTINGS_GID

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            parse_sheet_url("")
        with pytest.raises(ValueError):
            parse_sheet_url("   ")

    def test_invalid_url_raises(self):
        with pytest.raises(ValueError):
            parse_sheet_url("https://example.com/foo")

    def test_short_string_not_treated_as_id(self):
        # 20 文字未満の文字列は ID とみなさない (raise)
        with pytest.raises(ValueError):
            parse_sheet_url("short_id")

    def test_url_with_extra_path(self):
        url = "https://docs.google.com/spreadsheets/d/SHEETID12345_long_enough/edit#gid=0"
        sid, gid = parse_sheet_url(url)
        assert sid == "SHEETID12345_long_enough"
        assert gid == 0
