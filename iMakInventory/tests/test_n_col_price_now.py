"""N 列 (現在価格) 書込機能の regression test.

仕様:
- price_jpy が int (>=0) で渡された行のみ N 列書込
- price_jpy=None / 不在 / 非 int → N 列触らない (既存値維持)
- D/O 列のロジックは一切変えない (purely additive)
- 既存の o_only / D+O 書込パターンと組み合わせても正しく動作
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ============================================================================
# 列定数の存在確認
# ============================================================================
def test_n_col_constant_defined():
    """LISTINGS_COL_PRICE_NOW = 14 (N 列) が定義されている."""
    from sheet_updater import LISTINGS_COL_PRICE_NOW
    assert LISTINGS_COL_PRICE_NOW == 14


def test_existing_constants_unchanged():
    """既存列定数 (D/F/O 等) が変わっていないこと (在庫監視ロジック互換維持)."""
    from sheet_updater import (
        LISTINGS_COL_URL, LISTINGS_COL_ITEM_ID, LISTINGS_COL_TITLE,
        LISTINGS_COL_SOLD, LISTINGS_COL_PRICE, LISTINGS_COL_CHECKED_AT,
    )
    assert LISTINGS_COL_URL == 1
    assert LISTINGS_COL_ITEM_ID == 2
    assert LISTINGS_COL_TITLE == 3
    assert LISTINGS_COL_SOLD == 4         # D 列
    assert LISTINGS_COL_PRICE == 6        # F 列 (出品時価格、触らない)
    assert LISTINGS_COL_CHECKED_AT == 15  # O 列


# ============================================================================
# update_listings_sold_marks の N 列書込テスト
# ============================================================================
def test_price_jpy_writes_n_column():
    """price_jpy=int を渡すと N 列に書込される."""
    from sheet_updater import update_listings_sold_marks
    ws = MagicMock()
    ws.batch_update = MagicMock()

    updates = [
        {"row_index": 5, "checked_at": "t1", "o_only": True, "price_jpy": 12480},
    ]
    res = update_listings_sold_marks(ws, updates)

    assert res["updated"] == 1
    assert res["o_writes"] == 1
    assert res["d_writes"] == 0
    assert res["n_writes"] == 1

    args, _ = ws.batch_update.call_args
    cells = args[0]
    n_cell = next((c for c in cells if c["range"] == "N5"), None)
    assert n_cell is not None
    assert n_cell["values"] == [[12480]]


def test_price_jpy_none_skips_n_column():
    """price_jpy=None なら N 列を触らない (既存値維持)."""
    from sheet_updater import update_listings_sold_marks
    ws = MagicMock()
    ws.batch_update = MagicMock()

    updates = [
        {"row_index": 5, "checked_at": "t1", "o_only": True, "price_jpy": None},
    ]
    res = update_listings_sold_marks(ws, updates)

    assert res["n_writes"] == 0
    args, _ = ws.batch_update.call_args
    cells = args[0]
    assert "N5" not in [c["range"] for c in cells]


def test_price_jpy_absent_skips_n_column():
    """price_jpy フィールド不在なら N 列を触らない (=既存呼出側互換)."""
    from sheet_updater import update_listings_sold_marks
    ws = MagicMock()
    ws.batch_update = MagicMock()

    updates = [
        {"row_index": 5, "checked_at": "t1", "o_only": True},  # price_jpy 不在
    ]
    res = update_listings_sold_marks(ws, updates)

    assert res["n_writes"] == 0
    args, _ = ws.batch_update.call_args
    cells = args[0]
    assert "N5" not in [c["range"] for c in cells]


def test_price_jpy_non_int_skips_n_column():
    """非 int (str/float/bool) は N 列を触らない (型安全)."""
    from sheet_updater import update_listings_sold_marks
    ws = MagicMock()
    ws.batch_update = MagicMock()

    for bad in ["12480", 12480.5, True, False]:
        ws.reset_mock()
        updates = [{"row_index": 5, "checked_at": "t1", "o_only": True, "price_jpy": bad}]
        res = update_listings_sold_marks(ws, updates)
        assert res["n_writes"] == 0, f"bad value {bad!r} should be skipped"


def test_price_jpy_negative_skips_n_column():
    """負数は N 列を触らない (異常値防御)."""
    from sheet_updater import update_listings_sold_marks
    ws = MagicMock()
    ws.batch_update = MagicMock()

    updates = [{"row_index": 5, "checked_at": "t1", "o_only": True, "price_jpy": -1}]
    res = update_listings_sold_marks(ws, updates)
    assert res["n_writes"] == 0


def test_price_jpy_zero_writes_n_column():
    """0 円は書込 (None と区別、無料商品など想定)."""
    from sheet_updater import update_listings_sold_marks
    ws = MagicMock()
    ws.batch_update = MagicMock()

    updates = [{"row_index": 5, "checked_at": "t1", "o_only": True, "price_jpy": 0}]
    res = update_listings_sold_marks(ws, updates)
    assert res["n_writes"] == 1


def test_price_jpy_with_d_plus_o_combination():
    """変化あり (D+O) 行でも N 列書込が並行動作."""
    from sheet_updater import update_listings_sold_marks
    ws = MagicMock()
    ws.batch_update = MagicMock()

    updates = [
        {"row_index": 7, "is_sold": True, "checked_at": "t1", "price_jpy": 9800},
    ]
    res = update_listings_sold_marks(ws, updates)
    assert res["d_writes"] == 1
    assert res["o_writes"] == 1
    assert res["n_writes"] == 1
    args, _ = ws.batch_update.call_args
    ranges = sorted(c["range"] for c in args[0])
    assert ranges == sorted(["D7", "O7", "N7"])


def test_mixed_batch_with_n_writes():
    """同一 batch で N 列書込/スキップが混在しても正しく分離処理される."""
    from sheet_updater import update_listings_sold_marks
    ws = MagicMock()
    ws.batch_update = MagicMock()

    updates = [
        {"row_index": 2, "is_sold": True, "checked_at": "t", "price_jpy": 100},   # D+O+N
        {"row_index": 3, "checked_at": "t", "o_only": True, "price_jpy": 200},    # O+N
        {"row_index": 4, "checked_at": "t", "o_only": True},                       # O only (price 不在)
        {"row_index": 5, "is_sold": False, "checked_at": "t", "price_jpy": None}, # D+O (price None)
    ]
    res = update_listings_sold_marks(ws, updates)

    assert res["updated"] == 4
    assert res["d_writes"] == 2  # row 2, 5
    assert res["o_writes"] == 4  # 全行
    assert res["n_writes"] == 2  # row 2, 3 のみ

    args, _ = ws.batch_update.call_args
    ranges = sorted(c["range"] for c in args[0])
    assert ranges == sorted(["D2", "O2", "N2", "O3", "N3", "O4", "D5", "O5"])


def test_empty_returns_n_writes_zero():
    """updates 空でも n_writes キーが返る (既存呼出側に新キー追加されたことを保証)."""
    from sheet_updater import update_listings_sold_marks
    ws = MagicMock()
    res = update_listings_sold_marks(ws, [])
    assert res == {"updated": 0, "d_writes": 0, "o_writes": 0, "n_writes": 0, "ah_writes": 0}


# ============================================================================
# 既存挙動の non-regression 確認
# ============================================================================
def test_legacy_call_without_price_jpy_unchanged():
    """price_jpy 無し呼出は従来通り D+O のみ (既存呼出側互換)."""
    from sheet_updater import update_listings_sold_marks
    ws = MagicMock()
    ws.batch_update = MagicMock()

    # 既存 test_phase9_fix.py と同じ呼出パターン (price_jpy 無し)
    updates = [{"row_index": 7, "is_sold": True, "checked_at": "t1"}]
    res = update_listings_sold_marks(ws, updates)

    assert res["d_writes"] == 1
    assert res["o_writes"] == 1
    assert res["n_writes"] == 0  # 新キーは 0 (副作用なし)

    args, _ = ws.batch_update.call_args
    cells = args[0]
    ranges = [c["range"] for c in cells]
    assert "D7" in ranges
    assert "O7" in ranges
    assert "N7" not in ranges  # ← 重要: N 列に副作用なし


# ============================================================================
# monitor_listings.check_one_row が price_jpy を result に含めるか
# ============================================================================
def test_check_one_row_includes_price_jpy_field():
    """check_one_row の戻り値に price_jpy フィールドが含まれる."""
    import monitor_listings as ml

    # scraper をモック (in_stock=True, price_jpy=12480)
    fake_info = {
        "name": "test",
        "status": "ON_SALE",
        "skus": [{"in_stock": True, "price_jpy": 12480}],
    }
    orig = ml.fetch_mercari
    try:
        ml.fetch_mercari = lambda url, driver=None, use_selenium_fallback=False: fake_info
        row = {
            "row_index": 10,
            "url": "https://jp.mercari.com/item/m12345",
            "item_id": "999",
            "title": "test",
            "current_sold": "",
        }
        result = ml.check_one_row(row, sleep_sec=0)
    finally:
        ml.fetch_mercari = orig

    assert "price_jpy" in result
    assert result["price_jpy"] == 12480
    assert result["is_sold"] is False  # in_stock=True → not sold


def test_check_one_row_price_jpy_none_when_scraper_returns_none():
    """scraper が None を返した場合は price_jpy=None (N 列維持仕様)."""
    import monitor_listings as ml
    orig = ml.fetch_mercari
    try:
        ml.fetch_mercari = lambda url, driver=None, use_selenium_fallback=False: None
        row = {
            "row_index": 10,
            "url": "https://jp.mercari.com/item/m12345",
            "item_id": "999",
            "title": "test",
            "current_sold": "",
        }
        result = ml.check_one_row(row, sleep_sec=0)
    finally:
        ml.fetch_mercari = orig

    assert result["price_jpy"] is None
    assert result["error"] == "scraper returned None (fail-closed)"


def test_check_one_row_price_jpy_none_when_skus_price_missing():
    """skus[0].price_jpy が None でも result.price_jpy は None (上書きしない)."""
    import monitor_listings as ml
    fake_info = {
        "name": "test",
        "status": "DELETED",
        "skus": [{"in_stock": False, "price_jpy": None}],
    }
    orig = ml.fetch_mercari
    try:
        ml.fetch_mercari = lambda url, driver=None, use_selenium_fallback=False: fake_info
        row = {
            "row_index": 10,
            "url": "https://jp.mercari.com/item/m12345",
            "item_id": "999",
            "title": "test",
            "current_sold": "",
        }
        result = ml.check_one_row(row, sleep_sec=0)
    finally:
        ml.fetch_mercari = orig

    assert result["price_jpy"] is None
    assert result["is_sold"] is True
    assert result["raw_status"] == "DELETED"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
