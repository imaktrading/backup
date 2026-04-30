"""tests/test_sheet_writer_dedupe - append_new_urls の デデュープ / append-only 動作検証.

新仕様 (2026-04-30):
  - Harvest が書くのは A 列 URL のみ. B/C 列は空欄で書込.
  - デデュープキーは A 列 URL から dedupe_key() で抽出.
  - 既存行に B 列の値 (旧実装の item_id) があれば後方互換で併用.
"""
from __future__ import annotations

import pytest

from sheet_writer import (
    append_new_urls,
    dedupe_key,
    read_existing_dedupe_keys,
)


pytestmark = pytest.mark.offline


class _MockWorksheet:
    """get_all_values / append_rows のみ実装した最小モック."""

    def __init__(self, existing_rows: list[list[str]]):
        self._values = existing_rows
        self.append_calls: list[list[list[str]]] = []
        self.update_calls: list[tuple] = []
        self.batch_update_calls: list[list] = []

    def get_all_values(self):
        return self._values

    def append_rows(self, rows, value_input_option=None):  # noqa: ARG002
        self.append_calls.append(rows)

    def update(self, *args, **kwargs):  # noqa: ARG002
        self.update_calls.append((args, kwargs))

    def batch_update(self, *args, **kwargs):  # noqa: ARG002
        self.batch_update_calls.append((args, kwargs))


def _ws_with_existing_urls(item_ids: list[str]) -> _MockWorksheet:
    """A 列に URL のみ、B/C 列は空欄でモックを構築 (新仕様の既存スプシ)."""
    rows = [["URL", "", ""]]
    for iid in item_ids:
        rows.append([f"https://jp.mercari.com/item/{iid}", "", ""])
    return _MockWorksheet(rows)


def _ws_legacy_with_b_column(item_ids: list[str]) -> _MockWorksheet:
    """旧実装で B 列に item_id が入っている既存スプシ (後方互換テスト用)."""
    rows = [["URL", "item_id", "title"]]
    for iid in item_ids:
        rows.append([f"https://jp.mercari.com/item/{iid}", iid, ""])
    return _MockWorksheet(rows)


# --------------------------------------------------------------------------
# dedupe_key
# --------------------------------------------------------------------------
class TestDedupeKey:
    def test_mercari_item_url(self):
        assert dedupe_key("https://jp.mercari.com/item/m12345678901") == "m12345678901"

    def test_mercari_with_query(self):
        # ?ref=likes 等のクエリ違いを吸収
        assert dedupe_key("https://jp.mercari.com/item/m12345678901?ref=likes") == "m12345678901"

    def test_mercari_alt_path(self):
        assert dedupe_key("https://jp.mercari.com/items/m99999999999") == "m99999999999"

    def test_empty(self):
        assert dedupe_key("") == ""
        assert dedupe_key("   ") == ""

    def test_non_mercari_url_normalized(self):
        # mercari でなければ URL 正規化したものを返す
        k1 = dedupe_key("https://example.com/foo/bar?x=1#y")
        k2 = dedupe_key("https://example.com/foo/bar")
        assert k1 == k2


# --------------------------------------------------------------------------
# read_existing_dedupe_keys
# --------------------------------------------------------------------------
class TestReadExistingDedupeKeys:
    def test_extracts_keys_from_a_column_urls(self):
        ws = _ws_with_existing_urls(["m11111111111", "m22222222222"])
        assert read_existing_dedupe_keys(ws) == {"m11111111111", "m22222222222"}

    def test_empty_sheet(self):
        ws = _MockWorksheet([])
        assert read_existing_dedupe_keys(ws) == set()

    def test_header_only(self):
        ws = _MockWorksheet([["URL", "", ""]])
        assert read_existing_dedupe_keys(ws) == set()

    def test_skips_blank_a_cells(self):
        ws = _MockWorksheet([
            ["URL", "", ""],
            ["https://jp.mercari.com/item/m11111111111", "", ""],
            ["", "", ""],
        ])
        assert read_existing_dedupe_keys(ws) == {"m11111111111"}

    def test_legacy_b_column_values_are_kept_as_keys(self):
        # 旧実装で B 列に item_id が残っている行は後方互換で並行集計
        ws = _ws_legacy_with_b_column(["m11111111111", "m22222222222"])
        keys = read_existing_dedupe_keys(ws)
        # A 列 URL からも、B 列値からも、同じ item_id が key として入る
        assert keys == {"m11111111111", "m22222222222"}


# --------------------------------------------------------------------------
# append_new_urls
# --------------------------------------------------------------------------
class TestAppendNewUrls:
    def test_appends_only_new_items(self):
        ws = _ws_with_existing_urls(["m11111111111"])
        items = [
            {"url": "https://jp.mercari.com/item/m11111111111", "item_id": "m11111111111"},
            {"url": "https://jp.mercari.com/item/m22222222222", "item_id": "m22222222222"},
            {"url": "https://jp.mercari.com/item/m33333333333", "item_id": "m33333333333"},
        ]
        result = append_new_urls(ws, items)
        assert result == {"appended": 2, "skipped_existing": 1, "input": 3}
        assert len(ws.append_calls) == 1
        appended = ws.append_calls[0]
        assert [r[0] for r in appended] == [
            "https://jp.mercari.com/item/m22222222222",
            "https://jp.mercari.com/item/m33333333333",
        ]
        # B/C 列は常に空欄
        for r in appended:
            assert r[1] == ""
            assert r[2] == ""

    def test_writes_b_and_c_columns_empty(self):
        # 仕様: 入力 dict に item_id/title が入っていても B/C 列は空欄で書込
        ws = _ws_with_existing_urls([])
        items = [
            {"url": "https://jp.mercari.com/item/m11111111111",
             "item_id": "m11111111111", "title": "テスト商品"},
        ]
        append_new_urls(ws, items)
        appended = ws.append_calls[0]
        assert appended[0] == ["https://jp.mercari.com/item/m11111111111", "", ""]

    def test_skips_in_batch_duplicates(self):
        ws = _ws_with_existing_urls([])
        items = [
            {"url": "https://jp.mercari.com/item/m11111111111", "item_id": "m11111111111"},
            {"url": "https://jp.mercari.com/item/m11111111111?ref=likes", "item_id": "m11111111111"},
        ]
        result = append_new_urls(ws, items)
        # 2 件目はクエリ違いだが dedupe_key 同一 → skip される
        assert result["appended"] == 1
        assert result["skipped_existing"] == 1

    def test_dedupes_against_legacy_b_column(self):
        # 既存スプシの B 列に旧実装の item_id が残っていても、新規追加時はそれを
        # 既出として認識してスキップ.
        ws = _ws_legacy_with_b_column(["m11111111111"])
        items = [
            {"url": "https://jp.mercari.com/item/m11111111111", "item_id": "m11111111111"},
            {"url": "https://jp.mercari.com/item/m22222222222", "item_id": "m22222222222"},
        ]
        result = append_new_urls(ws, items)
        assert result["appended"] == 1
        assert result["skipped_existing"] == 1
        # 新規行も B/C 空欄で書込
        appended = ws.append_calls[0]
        assert appended[0] == ["https://jp.mercari.com/item/m22222222222", "", ""]

    def test_skips_invalid_items(self):
        ws = _ws_with_existing_urls([])
        items = [
            {"url": "", "item_id": "m11111111111"},                          # url 空
            {"url": "https://jp.mercari.com/item/m22222222222"},              # OK
        ]
        result = append_new_urls(ws, items)
        assert result["appended"] == 1
        assert result["skipped_existing"] == 1

    def test_does_not_call_update_or_batch_update(self):
        # 既存行を一切上書きしないことの担保 (CLAUDE.md: 既存スプシ行を上書きしない)
        ws = _ws_with_existing_urls(["m11111111111"])
        items = [
            {"url": "https://jp.mercari.com/item/m22222222222"},
        ]
        append_new_urls(ws, items)
        assert ws.update_calls == []
        assert ws.batch_update_calls == []

    def test_empty_input(self):
        ws = _ws_with_existing_urls([])
        result = append_new_urls(ws, [])
        assert result == {"appended": 0, "skipped_existing": 0, "input": 0}
        assert ws.append_calls == []

    def test_all_items_already_exist_no_append_call(self):
        ws = _ws_with_existing_urls(["m11111111111", "m22222222222"])
        items = [
            {"url": "https://jp.mercari.com/item/m11111111111"},
            {"url": "https://jp.mercari.com/item/m22222222222"},
        ]
        result = append_new_urls(ws, items)
        assert result["appended"] == 0
        assert result["skipped_existing"] == 2
        assert ws.append_calls == []
