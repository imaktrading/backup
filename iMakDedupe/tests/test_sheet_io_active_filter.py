"""sheet_io の ACTIVE filter 単体 test (= 2026-05-27 false positive 修正).

D 列 (= sold_col) 空欄の row のみ index 化 = `active_only=True` モード。
mock ws (get_all_values 直接) で network 不要。
"""

from unittest.mock import MagicMock

import pytest

from dedupe import sheet_io

pytestmark = pytest.mark.offline


def _ws_with_values(values):
    ws = MagicMock()
    ws.get_all_values.return_value = values
    ws.col_values.side_effect = lambda c: [r[c - 1] if len(r) >= c else "" for r in values]
    return ws


# row layout: A=URL, B=itemID, C=title, D=sold flag, ..., (key1, key2 末尾)
# 簡略化: col 1=URL / col 4=sold / col 5=KEY1 / col 6=KEY2
def _row(url="", item_id="", title="", sold="", key1="", key2=""):
    return [url, item_id, title, sold, key1, key2]


HEADER = ["URL", "itemID", "title", "売り切れ", "KEY1", "KEY2"]


class TestReadKeyColumnsTuplesActiveFilter:
    def test_all_active(self):
        """全 row D 列空欄 → 全件 index 化."""
        ws = _ws_with_values([
            HEADER,
            _row(key1="OP01-001", key2="alt"),
            _row(key1="OP01-002", key2=""),
        ])
        out = sheet_io.read_key_columns_tuples(
            ws, key1_col=5, key2_col=6, active_only=True, sold_col=4
        )
        assert out == [("OP01-001", "alt"), ("OP01-002", "")]

    def test_excludes_sold(self):
        """D 列 = `○` の row は index 外."""
        ws = _ws_with_values([
            HEADER,
            _row(key1="OP01-001", sold=""),         # ACTIVE
            _row(key1="OP01-002", sold="○"),         # 売切
            _row(key1="OP01-003", sold="取下げ"),     # 取下げ
            _row(key1="OP01-004", sold=""),         # ACTIVE
        ])
        out = sheet_io.read_key_columns_tuples(
            ws, key1_col=5, key2_col=6, active_only=True, sold_col=4
        )
        assert [t[0] for t in out] == ["OP01-001", "OP01-004"]

    def test_active_only_false_includes_all(self):
        """active_only=False (= default) → D 列無視で全 row."""
        ws = _ws_with_values([
            HEADER,
            _row(key1="OP01-001", sold=""),
            _row(key1="OP01-002", sold="○"),
        ])
        out = sheet_io.read_key_columns_tuples(
            ws, key1_col=5, key2_col=6, active_only=False
        )
        assert [t[0] for t in out] == ["OP01-001", "OP01-002"]

    def test_active_only_without_sold_col_no_filter(self):
        """sold_col=None なら active_only=True でも filter しない (= safety)."""
        ws = _ws_with_values([
            HEADER,
            _row(key1="OP01-001", sold=""),
            _row(key1="OP01-002", sold="○"),
        ])
        out = sheet_io.read_key_columns_tuples(
            ws, key1_col=5, key2_col=6, active_only=True, sold_col=None
        )
        assert [t[0] for t in out] == ["OP01-001", "OP01-002"]

    def test_empty_key1_skipped_in_both_modes(self):
        ws = _ws_with_values([
            HEADER,
            _row(key1="", sold=""),
            _row(key1="OP01-001", sold=""),
        ])
        out = sheet_io.read_key_columns_tuples(
            ws, key1_col=5, key2_col=6, active_only=True, sold_col=4
        )
        assert out == [("OP01-001", "")]

    def test_item_id_filter_excludes_unposted(self):
        """B 列 (item_id_col) 空欄 = 未出品 → index 外."""
        ws = _ws_with_values([
            HEADER,
            _row(item_id="358111", key1="OP01-001", sold=""),  # ACTIVE
            _row(item_id="", key1="OP01-002", sold=""),         # 未出品 → skip
            _row(item_id="358222", key1="OP01-003", sold=""),  # ACTIVE
            _row(item_id="358333", key1="OP01-004", sold="○"), # 売切 → skip
        ])
        out = sheet_io.read_key_columns_tuples(
            ws, key1_col=5, key2_col=6,
            active_only=True, sold_col=4, item_id_col=2,
        )
        assert [t[0] for t in out] == ["OP01-001", "OP01-003"]

    def test_item_id_filter_only(self):
        """sold_col 省略 + item_id_col のみ指定でも動作."""
        ws = _ws_with_values([
            HEADER,
            _row(item_id="358111", key1="OP01-001"),
            _row(item_id="", key1="OP01-002"),
        ])
        out = sheet_io.read_key_columns_tuples(
            ws, key1_col=5, key2_col=6,
            active_only=True, item_id_col=2,
        )
        assert [t[0] for t in out] == ["OP01-001"]


class TestReadKeyColumnValuesActiveFilter:
    def test_excludes_sold(self):
        ws = _ws_with_values([
            HEADER,
            _row(key1="OP01-001", sold=""),
            _row(key1="OP01-002", sold="○"),
            _row(key1="OP01-003", sold=""),
        ])
        out = sheet_io.read_key_column_values(
            ws, key_col=5, active_only=True, sold_col=4
        )
        assert out == ["OP01-001", "OP01-003"]

    def test_default_mode_uses_col_values(self):
        """active_only=False は col_values 経路 (= 既存挙動維持)."""
        ws = _ws_with_values([
            HEADER,
            _row(key1="OP01-001", sold=""),
            _row(key1="OP01-002", sold="○"),
        ])
        out = sheet_io.read_key_column_values(ws, key_col=5)
        # col_values で取得 → header skip 済の data 2 件
        assert out == ["OP01-001", "OP01-002"]

    def test_item_id_filter_excludes_unposted(self):
        ws = _ws_with_values([
            HEADER,
            _row(item_id="358111", key1="OP01-001", sold=""),  # ACTIVE
            _row(item_id="", key1="OP01-002", sold=""),         # 未出品 → skip
            _row(item_id="358333", key1="OP01-004", sold="○"), # 売切 → skip
        ])
        out = sheet_io.read_key_column_values(
            ws, key_col=5,
            active_only=True, sold_col=4, item_id_col=2,
        )
        assert out == ["OP01-001"]
