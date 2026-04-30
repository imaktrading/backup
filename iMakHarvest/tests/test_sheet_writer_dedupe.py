"""tests/test_sheet_writer_dedupe - append_new_urls の デデュープ / append-only 動作検証.

gspread Worksheet のモックで、既出 item_id を弾き、新規だけが append_rows に渡されること、
かつ既存行を一切 update しないこと (=append_rows 以外のメソッドが呼ばれないこと) を検証。
"""
from __future__ import annotations

import pytest

from sheet_writer import append_new_urls, read_existing_item_ids


pytestmark = pytest.mark.offline


class _MockWorksheet:
    """get_all_values / append_rows のみ実装した最小モック."""

    def __init__(self, existing_rows: list[list[str]]):
        # 1 行目を header と見なす
        self._values = existing_rows
        self.append_calls: list[list[list[str]]] = []
        self.update_calls: list[tuple] = []
        self.batch_update_calls: list[list] = []

    def get_all_values(self):
        return self._values

    def append_rows(self, rows, value_input_option=None):  # noqa: ARG002
        self.append_calls.append(rows)

    # 念のため: もし update / batch_update が呼ばれたらテストで検出できるよう実装
    def update(self, *args, **kwargs):  # noqa: ARG002
        self.update_calls.append((args, kwargs))

    def batch_update(self, *args, **kwargs):  # noqa: ARG002
        self.batch_update_calls.append((args, kwargs))


def _ws_with_existing(item_ids: list[str]) -> _MockWorksheet:
    rows = [["URL", "item_id", "title"]]
    for iid in item_ids:
        rows.append([f"https://jp.mercari.com/item/{iid}", iid, ""])
    return _MockWorksheet(rows)


# --------------------------------------------------------------------------
# read_existing_item_ids
# --------------------------------------------------------------------------
class TestReadExistingItemIds:
    def test_extracts_item_ids_from_b_column(self):
        ws = _ws_with_existing(["m11111111111", "m22222222222"])
        assert read_existing_item_ids(ws) == {"m11111111111", "m22222222222"}

    def test_empty_sheet(self):
        ws = _MockWorksheet([])
        assert read_existing_item_ids(ws) == set()

    def test_header_only(self):
        ws = _MockWorksheet([["URL", "item_id", "title"]])
        assert read_existing_item_ids(ws) == set()

    def test_skips_blank_b_cells(self):
        ws = _MockWorksheet([
            ["URL", "item_id", "title"],
            ["https://...", "m11111111111", ""],
            ["https://...", "", ""],
        ])
        assert read_existing_item_ids(ws) == {"m11111111111"}


# --------------------------------------------------------------------------
# append_new_urls
# --------------------------------------------------------------------------
class TestAppendNewUrls:
    def test_appends_only_new_items(self):
        ws = _ws_with_existing(["m11111111111"])
        items = [
            {"url": "https://jp.mercari.com/item/m11111111111", "item_id": "m11111111111"},
            {"url": "https://jp.mercari.com/item/m22222222222", "item_id": "m22222222222"},
            {"url": "https://jp.mercari.com/item/m33333333333", "item_id": "m33333333333"},
        ]
        result = append_new_urls(ws, items)
        assert result == {"appended": 2, "skipped_existing": 1, "input": 3}
        assert len(ws.append_calls) == 1
        appended = ws.append_calls[0]
        assert [r[1] for r in appended] == ["m22222222222", "m33333333333"]
        assert [r[0] for r in appended] == [
            "https://jp.mercari.com/item/m22222222222",
            "https://jp.mercari.com/item/m33333333333",
        ]

    def test_skips_in_batch_duplicates(self):
        # 同一 batch 内に同じ item_id が 2 件あっても 1 件しか追加しない
        ws = _ws_with_existing([])
        items = [
            {"url": "https://jp.mercari.com/item/m11111111111", "item_id": "m11111111111"},
            {"url": "https://jp.mercari.com/item/m11111111111", "item_id": "m11111111111"},
        ]
        result = append_new_urls(ws, items)
        assert result["appended"] == 1
        assert result["skipped_existing"] == 1

    def test_skips_invalid_items(self):
        ws = _ws_with_existing([])
        items = [
            {"url": "", "item_id": "m11111111111"},
            {"url": "https://jp.mercari.com/item/m22222222222", "item_id": ""},
            {"url": "https://jp.mercari.com/item/m33333333333", "item_id": "m33333333333"},
        ]
        result = append_new_urls(ws, items)
        assert result["appended"] == 1
        assert result["skipped_existing"] == 2

    def test_does_not_call_update_or_batch_update(self):
        # 既存行を一切上書きしないことの担保 (CLAUDE.md: 既存スプシ行を上書きしない)
        ws = _ws_with_existing(["m11111111111"])
        items = [
            {"url": "https://jp.mercari.com/item/m22222222222", "item_id": "m22222222222"},
        ]
        append_new_urls(ws, items)
        assert ws.update_calls == []
        assert ws.batch_update_calls == []

    def test_empty_input(self):
        ws = _ws_with_existing([])
        result = append_new_urls(ws, [])
        assert result == {"appended": 0, "skipped_existing": 0, "input": 0}
        assert ws.append_calls == []

    def test_all_items_already_exist_no_append_call(self):
        ws = _ws_with_existing(["m11111111111", "m22222222222"])
        items = [
            {"url": "https://jp.mercari.com/item/m11111111111", "item_id": "m11111111111"},
            {"url": "https://jp.mercari.com/item/m22222222222", "item_id": "m22222222222"},
        ]
        result = append_new_urls(ws, items)
        assert result["appended"] == 0
        assert result["skipped_existing"] == 2
        assert ws.append_calls == []

    def test_includes_title_when_provided(self):
        ws = _ws_with_existing([])
        items = [
            {"url": "https://jp.mercari.com/item/m11111111111", "item_id": "m11111111111", "title": "テスト商品"},
        ]
        append_new_urls(ws, items)
        appended = ws.append_calls[0]
        assert appended[0][2] == "テスト商品"
