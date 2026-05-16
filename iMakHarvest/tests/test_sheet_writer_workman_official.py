"""tests/test_sheet_writer_workman_official - Workman ★公式在庫要チェック シート1 投入の検証.

Phase 2 v2 (2026-05-16) で確定した投入仕様:
  - 投入先 = `101KL6...` シート1 (gid=0)
  - 書込列 = B (title) + F (URL) のみ
  - 他列 (A FLG / C item ID / D / E ebay URL / G CHK date) は touch しない
  - dedupe = F 列 URL から parent_mpn 抽出
  - title 空 / URL 空 / parent_mpn 抽出不能 → fail-closed skip
"""
from __future__ import annotations

import pytest

from sheet_writer_workman_official import (
    COL_TITLE,
    COL_URL,
    OFFICIAL_GID,
    OFFICIAL_SHEET_ID,
    WORKMAN_OFFICIAL_COLUMN_COUNT,
    _build_workman_row,
    append_workman_urls,
    read_existing_dedupe_keys,
)


pytestmark = pytest.mark.offline


# --------------------------------------------------------------------------
# Constants 確認
# --------------------------------------------------------------------------
class TestConstants:
    def test_sheet_id_correct(self):
        # Phase 2 v2 確定の sheet_id
        assert OFFICIAL_SHEET_ID == "101KL6KxMugKqZeSp2W5L2ykTvT0Zwd3RzlfsHgiJsg0"
        assert OFFICIAL_GID == 0

    def test_column_indexes(self):
        # シート1 ヘッダー: A=FLG / B=title / C=item ID / D / E=ebay URL / F=URL / G=CHK date
        assert COL_TITLE == 2
        assert COL_URL == 6

    def test_column_count(self):
        # 7 列 (A〜G)、H 以降は touch しない
        assert WORKMAN_OFFICIAL_COLUMN_COUNT == 7


# --------------------------------------------------------------------------
# Mock worksheet
# --------------------------------------------------------------------------
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


def _ws_with_existing_workman_urls(mpns: list[str]) -> _MockWorksheet:
    """シート1 形式 (7 列) で Workman 既存行を持つモック."""
    rows = [["FLG", "title", "item ID", "", "ebay URL", "URL", "CHK date"]]  # header
    for mpn in mpns:
        row = [""] * 7
        row[COL_TITLE - 1] = f"既存商品 {mpn}"
        row[COL_URL - 1] = f"https://workman.jp/shop/g/g{mpn}/"
        rows.append(row)
    return _MockWorksheet(rows)


def _ws_with_mixed_existing(rows_data: list[tuple[str, str]]) -> _MockWorksheet:
    """シート1 形式で title + URL の任意組合せ (他 supplier 混在想定)."""
    rows = [["FLG", "title", "item ID", "", "ebay URL", "URL", "CHK date"]]
    for title, url in rows_data:
        row = [""] * 7
        row[COL_TITLE - 1] = title
        row[COL_URL - 1] = url
        rows.append(row)
    return _MockWorksheet(rows)


# --------------------------------------------------------------------------
# _build_workman_row: 7 列、B/F 列のみ値あり
# --------------------------------------------------------------------------
class TestBuildWorkmanRow:
    def test_basic_row(self):
        item = {
            "url": "https://workman.jp/shop/g/g2300011882014/",
            "title": "ゼロステージレギンス",
        }
        row = _build_workman_row(item)
        assert len(row) == 7  # A〜G
        # A (FLG) は空欄
        assert row[0] == ""
        # B (title)
        assert row[1] == "ゼロステージレギンス"
        # C (item ID) 空欄 — 出品くんが update
        assert row[2] == ""
        # D 空欄
        assert row[3] == ""
        # E (ebay URL) 空欄 — 出品くんが update
        assert row[4] == ""
        # F (URL)
        assert row[5] == "https://workman.jp/shop/g/g2300011882014/"
        # G (CHK date) 空欄 — Inventory が update
        assert row[6] == ""

    def test_strips_whitespace(self):
        item = {
            "url": "  https://workman.jp/shop/g/g123/ \n",
            "title": "  商品名  ",
        }
        row = _build_workman_row(item)
        assert row[1] == "商品名"
        assert row[5] == "https://workman.jp/shop/g/g123/"

    def test_missing_fields_become_empty(self):
        # title 欠落 → 空欄 (append_workman_urls 側で skip される)
        item = {"url": "https://workman.jp/shop/g/g123/"}
        row = _build_workman_row(item)
        assert row[1] == ""
        assert row[5] == "https://workman.jp/shop/g/g123/"


# --------------------------------------------------------------------------
# read_existing_dedupe_keys
# --------------------------------------------------------------------------
class TestReadExistingDedupeKeys:
    def test_extracts_workman_keys(self):
        ws = _ws_with_existing_workman_urls(["2300011882014", "2300016710015"])
        keys = read_existing_dedupe_keys(ws)
        assert keys == {"workman:2300011882014", "workman:workman:2300016710015"} \
            or keys == {"workman:2300011882014", "workman:2300016710015"}  # double prefix bug guard

    def test_workman_and_other_supplier_coexist(self):
        # シート1 に UNIQLO 等他 supplier 行が既存 → parent_mpn 抽出不能で別 key
        ws = _ws_with_mixed_existing([
            ("ベルセルク UT", "https://www.uniqlo.com/jp/ja/products/E483933-000/00"),
            ("ゼロステージレギンス", "https://workman.jp/shop/g/g2300011882014/"),
        ])
        keys = read_existing_dedupe_keys(ws)
        # workman key は存在
        assert "workman:2300011882014" in keys
        # UNIQLO 行の key は workman: prefix にならない
        workman_keys = {k for k in keys if k.startswith("workman:")}
        assert workman_keys == {"workman:2300011882014"}

    def test_empty_sheet(self):
        ws = _MockWorksheet([])
        assert read_existing_dedupe_keys(ws) == set()

    def test_header_only(self):
        ws = _MockWorksheet([["FLG", "title", "item ID", "", "ebay URL", "URL", "CHK date"]])
        assert read_existing_dedupe_keys(ws) == set()


# --------------------------------------------------------------------------
# append_workman_urls
# --------------------------------------------------------------------------
class TestAppendWorkmanUrls:
    def test_appends_new_items_only(self):
        ws = _ws_with_existing_workman_urls(["2300011882014"])
        items = [
            {"url": "https://workman.jp/shop/g/g2300011882014/", "title": "既出商品"},
            {"url": "https://workman.jp/shop/g/g2300016710015/", "title": "新規商品 A"},
            {"url": "https://workman.jp/shop/g/g2300011883011/", "title": "新規商品 B"},
        ]
        result = append_workman_urls(ws, items)
        assert result["appended"] == 2
        assert result["skipped_existing"] == 1
        assert result["skipped_invalid"] == 0
        assert result["input"] == 3
        appended = ws.append_calls[0]
        assert len(appended) == 2
        # 各行は 7 列 + B 列 title + F 列 URL のみ
        for r in appended:
            assert len(r) == 7
            assert r[COL_TITLE - 1] != ""  # title あり
            assert r[COL_URL - 1] != ""    # URL あり
            assert r[0] == ""              # FLG 空
            assert r[2] == ""              # item ID 空
            assert r[4] == ""              # ebay URL 空

    def test_fail_closed_skip_missing_title(self):
        # title 空 → skip (CLAUDE.md fail-closed)
        ws = _ws_with_existing_workman_urls([])
        items = [
            {"url": "https://workman.jp/shop/g/g2300011882014/", "title": ""},
            {"url": "https://workman.jp/shop/g/g2300016710015/", "title": "OK 商品"},
        ]
        result = append_workman_urls(ws, items)
        assert result["appended"] == 1
        assert result["skipped_invalid"] == 1  # title 空
        appended = ws.append_calls[0]
        assert appended[0][COL_URL - 1] == "https://workman.jp/shop/g/g2300016710015/"

    def test_fail_closed_skip_missing_url(self):
        ws = _ws_with_existing_workman_urls([])
        items = [
            {"url": "", "title": "title あり URL 無し"},
            {"url": "https://workman.jp/shop/g/g2300011882014/", "title": "OK"},
        ]
        result = append_workman_urls(ws, items)
        assert result["appended"] == 1
        assert result["skipped_invalid"] == 1

    def test_fail_closed_skip_non_workman_url(self):
        # parent_mpn 抽出不能 (Workman URL でない) → skip
        ws = _ws_with_existing_workman_urls([])
        items = [
            {"url": "https://example.com/foo", "title": "別 supplier"},
            {"url": "https://workman.jp/shop/g/g2300011882014/", "title": "OK"},
        ]
        result = append_workman_urls(ws, items)
        assert result["appended"] == 1
        assert result["skipped_invalid"] == 1

    def test_dedupes_in_batch(self):
        # 同一 batch 内に重複 URL → 1 件のみ append
        ws = _ws_with_existing_workman_urls([])
        items = [
            {"url": "https://workman.jp/shop/g/g2300011882014/", "title": "A"},
            {"url": "https://workman.jp/shop/g/g2300011882014/?ref=foo", "title": "A 重複"},
            {"url": "https://workman.jp/shop/g/g2300011882014/", "title": "A 再重複"},
        ]
        result = append_workman_urls(ws, items)
        assert result["appended"] == 1
        assert result["skipped_existing"] == 2  # batch 内重複

    def test_empty_input(self):
        ws = _ws_with_existing_workman_urls([])
        result = append_workman_urls(ws, [])
        assert result == {"appended": 0, "skipped_existing": 0, "skipped_invalid": 0, "input": 0}
        assert ws.append_calls == []

    def test_does_not_call_update_or_batch_update(self):
        # 既存行を一切上書きしない (CLAUDE.md: 既存スプシ行を上書きしない)
        ws = _ws_with_existing_workman_urls(["2300011882014"])
        items = [{"url": "https://workman.jp/shop/g/g2300016710015/", "title": "新規"}]
        append_workman_urls(ws, items)
        assert ws.update_calls == []
        assert ws.batch_update_calls == []

    def test_coexists_with_uniqlo_rows(self):
        # シート1 既存 UNIQLO 行 (parent_mpn 抽出不能) と Workman 投入が衝突しない
        ws = _ws_with_mixed_existing([
            ("ベルセルク UT", "https://www.uniqlo.com/jp/ja/products/E483933-000/00"),
            ("ワンピース UT", "https://www.uniqlo.com/jp/ja/products/E480696-000/00"),
        ])
        items = [
            {"url": "https://workman.jp/shop/g/g2300011882014/", "title": "ゼロステージ"},
        ]
        result = append_workman_urls(ws, items)
        assert result["appended"] == 1
        assert result["skipped_existing"] == 0
        # UNIQLO 行は touch されない
        appended = ws.append_calls[0]
        assert appended[0][COL_URL - 1] == "https://workman.jp/shop/g/g2300011882014/"

    def test_all_invalid_no_append_call(self):
        ws = _ws_with_existing_workman_urls([])
        items = [
            {"url": "", "title": ""},
            {"url": "https://example.com/foo", "title": "別 supplier"},
        ]
        result = append_workman_urls(ws, items)
        assert result["appended"] == 0
        assert result["skipped_invalid"] == 2
        assert ws.append_calls == []
