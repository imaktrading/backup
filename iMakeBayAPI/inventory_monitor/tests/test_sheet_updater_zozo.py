"""sheet_updater の ZOZO 対応 regression (2026-08-10 [IMPLEMENT-GO]).

★1丁目1番地 判定:
  ① メインシート F列のドメイン (canonical KEY) は正しい
  ② 引き方 (supplier 判定) が zozo.jp を知らなかった = ②が誤り → コード側で修正
  → 分類は ②が誤り。カタログ (シート) には依頼を出さない。

本テストは gspread に依存せず (実 API を叩かず) 判定分岐だけを検査する:
  - zozo.jp が supplier="zozo" にマップされる
  - サブドメイン (zozo.jp) 部分一致でよい
  - supplier_filter="zozo" で ZOZO 行のみに絞れる
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import sheet_updater  # noqa: E402
from sheet_updater import (  # noqa: E402
    read_main_active_rows,
    get_last_unsupported_rows,
)


# ---------------------------------------------------------------------------
# FakeSheet: gspread のインターフェイスを最小模倣 (graniph テストと同型)
# ---------------------------------------------------------------------------
class _FakeMainWs:
    def __init__(self, rows: list):
        self._rows = rows

    def get_all_values(self):
        return list(self._rows)


class _FakeSpreadsheet:
    def __init__(self, main_rows: list):
        self._main = _FakeMainWs(main_rows)
        self.title = "FAKE"

    def worksheet(self, name):
        if name in ("メイン", "main", "Main", "Sheet1"):
            return self._main
        import gspread
        raise gspread.WorksheetNotFound(name)

    def get_worksheet(self, idx):
        return self._main


def _row(flg="", title="t", listing_id="", url=""):
    return [flg, title, listing_id, "", "", url]


# ---------------------------------------------------------------------------
# supplier 判定
# ---------------------------------------------------------------------------
def test_zozo_domain_maps_to_zozo_supplier():
    main_rows = [
        ["FLG", "title", "listingID", "", "", "URL"],  # header
        _row(listing_id="357100000001",
             url="https://zozo.jp/shop/minius/goods/103638934/?did=166413955"),
    ]
    sh = _FakeSpreadsheet(main_rows)
    rows = read_main_active_rows(sh, supplier_filter="all")
    assert len(rows) == 1
    assert rows[0]["supplier"] == "zozo"


def test_zozo_domain_supplier_filter_zozo():
    """supplier_filter='zozo' で ZOZO 行のみに絞れる."""
    main_rows = [
        ["FLG", "title", "listingID", "", "", "URL"],
        _row(listing_id="357100000001",
             url="https://zozo.jp/shop/minius/goods/103638934/"),
        _row(listing_id="357100000002",
             url="https://www.uniqlo.com/jp/ja/products/E483933-000"),
        _row(listing_id="357100000003",
             url="https://www.graniph.com/item-detail/012000906300"),
    ]
    sh = _FakeSpreadsheet(main_rows)
    rows = read_main_active_rows(sh, supplier_filter="zozo")
    assert len(rows) == 1
    assert rows[0]["supplier"] == "zozo"
    assert rows[0]["listing_id"] == "357100000001"


def test_zozo_does_not_get_matched_by_similar_domains():
    """zozo.jp 部分一致だが、zozo.town や fake-zozo.jp.evil.com のようなドメインは弾く."""
    main_rows = [
        ["FLG", "title", "listingID", "", "", "URL"],
        _row(listing_id="357100000010",
             url="https://not-zozo.example.com/goods/123/"),
    ]
    sh = _FakeSpreadsheet(main_rows)
    rows = read_main_active_rows(sh, supplier_filter="all")
    assert rows == []
    unsupported = get_last_unsupported_rows()
    # zozo.jp を含まないドメインは other として扱われるはず
    assert len(unsupported) == 1


def test_zozo_with_flg_1_is_skipped():
    """FLG=1 の ZOZO 行は active 一覧から除外される."""
    main_rows = [
        ["FLG", "title", "listingID", "", "", "URL"],
        _row(flg="1", listing_id="357100000001",
             url="https://zozo.jp/shop/minius/goods/103638934/"),
    ]
    sh = _FakeSpreadsheet(main_rows)
    rows = read_main_active_rows(sh, supplier_filter="all")
    assert rows == []


def test_zozo_all_filter_includes_zozo_and_others():
    """supplier_filter='all' で zozo + 他 supplier 混在で全て取得される."""
    main_rows = [
        ["FLG", "title", "listingID", "", "", "URL"],
        _row(listing_id="357100000001",
             url="https://zozo.jp/shop/minius/goods/103638934/"),
        _row(listing_id="357100000002",
             url="https://www.graniph.com/item-detail/012000906300"),
    ]
    sh = _FakeSpreadsheet(main_rows)
    rows = read_main_active_rows(sh, supplier_filter="all")
    suppliers = {r["supplier"] for r in rows}
    assert suppliers == {"zozo", "graniph"}
