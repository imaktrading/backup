"""sheet_updater の graniph 対応 + silent-drop 可視化 regression (2026-08-08 [IMPLEMENT-GO]).

★1丁目1番地 判定:
  ① メインシート F列のドメイン (canonical KEY) は正しい
  ② 引き方 (supplier 判定) が graniph.com を知らなかった = ②が誤り → コード側で修正
  → 分類は ②が誤り。カタログ (シート) には依頼を出さない。

本テストは gspread に依存せず (実 API を叩かず) 判定分岐だけを検査する:
  - graniph.com が supplier="graniph" にマップされる
  - 未対応ドメインが silent drop されず _last_unsupported_rows に記録される
  - update_sku_rows の U 列書込ロジック (list_price あり → 数値、無し → 空欄)
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
    update_sku_rows,
    SKU_COL_LIST_PRICE,
)


# ---------------------------------------------------------------------------
# FakeSheet: gspread のインターフェイスを最小模倣
# ---------------------------------------------------------------------------
class _FakeMainWs:
    def __init__(self, rows: list):
        self._rows = rows

    def get_all_values(self):
        return list(self._rows)


class _FakeSkuWs:
    """SKU詳細シート mock. update_sku_rows の batch_update を記録する."""
    def __init__(self, existing: Optional[list] = None):
        # rows: list[list[str]] (header 含む)
        self.rows = list(existing) if existing else [
            ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L",
             "M", "N", "O", "P", "Q", "R", "S", "T", "U"],
        ]
        self.col_count = 21
        self.row_count = max(len(self.rows), 1)
        self.batches: list = []

    def get_all_values(self):
        return list(self.rows)

    def add_rows(self, n):
        self.row_count += n

    def add_cols(self, n):
        self.col_count += n

    def batch_update(self, cell_updates, value_input_option="USER_ENTERED"):
        self.batches.append(cell_updates)


class _FakeSpreadsheet:
    def __init__(self, main_rows: list, sku_rows: Optional[list] = None):
        self._main = _FakeMainWs(main_rows)
        self._sku = _FakeSkuWs(sku_rows)
        self.title = "FAKE"

    def worksheet(self, name):
        if name == sheet_updater.SKU_TAB_NAME:
            return self._sku
        # メインシート worksheet lookup 対象 (メイン/main/Main/Sheet1)
        if name in ("メイン", "main", "Main", "Sheet1"):
            return self._main
        import gspread
        raise gspread.WorksheetNotFound(name)

    def get_worksheet(self, idx):
        return self._main


# ---------------------------------------------------------------------------
# read_main_active_rows: supplier 判定 + silent drop
# ---------------------------------------------------------------------------
def _row(flg="", title="t", listing_id="", url=""):
    """FLG A / title B / listing C / (空 D) / (空 E) / URL F の 6 列を返す."""
    return [flg, title, listing_id, "", "", url]


def test_graniph_domain_maps_to_graniph_supplier():
    main_rows = [
        ["FLG", "title", "listingID", "", "", "URL"],  # header
        _row(listing_id="357000000001",
             url="https://www.graniph.com/item-detail/012000906300"),
    ]
    sh = _FakeSpreadsheet(main_rows)
    rows = read_main_active_rows(sh, supplier_filter="all")
    assert len(rows) == 1
    assert rows[0]["supplier"] == "graniph"


def test_graniph_domain_supplier_filter_graniph():
    main_rows = [
        ["FLG", "title", "listingID", "", "", "URL"],
        _row(listing_id="357000000001",
             url="https://www.graniph.com/item-detail/012000906300"),
        _row(listing_id="357000000002",
             url="https://www.uniqlo.com/jp/ja/products/E483933-000"),
    ]
    sh = _FakeSpreadsheet(main_rows)
    rows = read_main_active_rows(sh, supplier_filter="graniph")
    assert len(rows) == 1
    assert rows[0]["supplier"] == "graniph"
    assert rows[0]["listing_id"] == "357000000001"


def test_unsupported_domain_is_recorded_not_silent():
    """★§6 silent drop の可視化: 未対応ドメインが _last_unsupported_rows に残る."""
    main_rows = [
        ["FLG", "title", "listingID", "", "", "URL"],
        _row(listing_id="357000000099",
             url="https://www.rakuten.co.jp/some/item/12345"),
    ]
    sh = _FakeSpreadsheet(main_rows)
    rows = read_main_active_rows(sh, supplier_filter="all")
    assert rows == []
    unsupported = get_last_unsupported_rows()
    assert len(unsupported) == 1
    assert "rakuten" in unsupported[0]["domain"]
    assert unsupported[0]["row_index"] == 2   # header=1、data 開始=2


def test_get_last_unsupported_reset_between_calls():
    """複数回呼んでも前回分が残らない (常に最新分だけ)."""
    main_rows_1 = [["FLG", "t", "l", "", "", "URL"],
                   _row(listing_id="1", url="https://unknown.example.com/x")]
    main_rows_2 = [["FLG", "t", "l", "", "", "URL"],
                   _row(listing_id="2",
                        url="https://www.uniqlo.com/jp/ja/products/E1-000")]
    read_main_active_rows(_FakeSpreadsheet(main_rows_1), supplier_filter="all")
    assert len(get_last_unsupported_rows()) == 1
    read_main_active_rows(_FakeSpreadsheet(main_rows_2), supplier_filter="all")
    assert get_last_unsupported_rows() == []


def test_flg_1_row_is_skipped():
    main_rows = [
        ["FLG", "title", "listingID", "", "", "URL"],
        _row(flg="1", listing_id="357000000001",
             url="https://www.graniph.com/item-detail/012000906300"),
    ]
    sh = _FakeSpreadsheet(main_rows)
    rows = read_main_active_rows(sh, supplier_filter="all")
    assert rows == []


# ---------------------------------------------------------------------------
# update_sku_rows: U 列 (list_price) 書込
# ---------------------------------------------------------------------------
def test_U_column_written_as_number_when_list_price_present():
    """graniph/uniqlo は base=定価 が判るので U に数値書込."""
    sh = _FakeSpreadsheet(main_rows=[["FLG"]])   # main は使わない
    updates = [{
        "row_index": None,     # append
        "listing_id": "357000000001",
        "title": "test",
        "sku_id": "SKU-1",
        "size": "L",
        "color": "ブラウン",
        "supplier_stock_mark": "◎",
        "supplier_price": 7990,
        "list_price": 8900,
        "ebay_qty": 0,
        "auto_check_at": "2026/08/08 10:00",
        "needs_action": True,
    }]
    update_sku_rows(sh, updates)
    batches = sh._sku.batches
    assert len(batches) == 1
    # 3 entries per row: A:L, Q, U
    entries = batches[0]
    u_entry = next(e for e in entries if e["range"].startswith("U"))
    assert u_entry["values"] == [[8900]]


def test_U_column_written_empty_when_list_price_none():
    """workman/montbell/amazon は base/promo 区別不能なので U 空欄."""
    sh = _FakeSpreadsheet(main_rows=[["FLG"]])
    updates = [{
        "row_index": None,
        "listing_id": "357000000002",
        "title": "test",
        "sku_id": "",
        "size": "",
        "color": "",
        "supplier_stock_mark": "◎",
        "supplier_price": 1500,
        # list_price キー無し = None 相当
        "ebay_qty": 0,
        "auto_check_at": "2026/08/08 10:00",
        "needs_action": False,
    }]
    update_sku_rows(sh, updates)
    entries = sh._sku.batches[0]
    u_entry = next(e for e in entries if e["range"].startswith("U"))
    assert u_entry["values"] == [[""]]


def test_U_column_written_empty_when_list_price_empty_string():
    """欠損表現に "" が紛れ込んでも 0 円扱いしない (fail-closed)."""
    sh = _FakeSpreadsheet(main_rows=[["FLG"]])
    updates = [{
        "row_index": None,
        "listing_id": "357000000003",
        "title": "test",
        "sku_id": "",
        "size": "",
        "color": "",
        "supplier_stock_mark": "◎",
        "supplier_price": 1500,
        "list_price": "",  # 欠損
        "ebay_qty": 0,
        "auto_check_at": "2026/08/08 10:00",
        "needs_action": False,
    }]
    update_sku_rows(sh, updates)
    entries = sh._sku.batches[0]
    u_entry = next(e for e in entries if e["range"].startswith("U"))
    assert u_entry["values"] == [[""]]


def test_SKU_COL_LIST_PRICE_is_21():
    """U 列 = 21 番目であることの回帰ガード (窓口実測: 既存 col_count 20→21 拡張済)."""
    assert SKU_COL_LIST_PRICE == 21
