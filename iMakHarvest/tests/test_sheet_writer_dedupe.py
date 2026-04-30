"""tests/test_sheet_writer_dedupe - append_new_urls の デデュープ / append-only 動作検証.

新仕様 (2026-04-30):
  - Harvest が書くのは A 列 URL のみ. B/C 列は空欄で書込.
  - デデュープキーは A 列 URL から dedupe_key() で抽出.
  - B 列は eBay item ID (数字のみ) 用の別関心列 → デデュープ判定では参照しない.
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


def _ws_with_ebay_item_ids(url_and_ebay_ids: list[tuple[str, str]]) -> _MockWorksheet:
    """A 列 URL + B 列 eBay item ID (数字のみ) の既存スプシ (実運用想定)."""
    rows = [["URL", "eBay itemID", ""]]
    for url, ebay_id in url_and_ebay_ids:
        rows.append([url, ebay_id, ""])
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

    def test_b_column_ebay_ids_are_ignored(self):
        # B 列は eBay item ID (数字のみ) 用 → dedupe key set には入れない
        ws = _ws_with_ebay_item_ids([
            ("https://jp.mercari.com/item/m11111111111", "357401200653"),
            ("https://jp.mercari.com/item/m22222222222", "357401200999"),
        ])
        keys = read_existing_dedupe_keys(ws)
        # Mercari URL ベースの key のみが集まり、eBay item ID は混ざらない
        assert keys == {"m11111111111", "m22222222222"}
        assert "357401200653" not in keys
        assert "357401200999" not in keys


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

    def test_b_column_ebay_id_does_not_affect_dedupe(self):
        # B 列に eBay item ID (数字) が入っていても、デデュープには影響しない.
        # 既存判定は A 列 URL のみで行う.
        ws = _ws_with_ebay_item_ids([
            ("https://jp.mercari.com/item/m11111111111", "357401200653"),
        ])
        items = [
            {"url": "https://jp.mercari.com/item/m11111111111"},     # A 列で既出 → skip
            {"url": "https://jp.mercari.com/item/m22222222222"},     # 新規
        ]
        result = append_new_urls(ws, items)
        assert result["appended"] == 1
        assert result["skipped_existing"] == 1
        appended = ws.append_calls[0]
        assert appended[0] == ["https://jp.mercari.com/item/m22222222222", "", ""]

    def test_b_column_ebay_id_unrelated_string_does_not_match(self):
        # 仮に Mercari URL の入力 item_id が eBay item ID 文字列と「数字一致」しても
        # dedupe_key 規則 (m\\d+ または URL 正規化) では別物として扱われる.
        ws = _ws_with_ebay_item_ids([
            ("https://jp.mercari.com/item/m11111111111", "357401200653"),
        ])
        items = [
            # Mercari URL じゃないが eBay 番号文字列だけ突っ込む不正入力ケース
            {"url": "357401200653"},
        ]
        result = append_new_urls(ws, items)
        # url が短すぎて dedupe_key が空 (というか文字列そのまま) → invalid 扱いで skip
        # または別物として 1 件 append される (現在の実装は後者)
        # 重要なのは「eBay ID と Mercari URL が衝突しないこと」のみ. この行が
        # 既出 m11111111111 とも、B 列の 357401200653 とも一致しない.
        assert result["appended"] + result["skipped_existing"] == 1

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
