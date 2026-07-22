"""M 列 (現在価格) / K 列 (基本ポイント) 書込機能の regression test.

★ 2026-07-22 HQ 依頼で「書き手は観測値のみ・N はシート関数」設計へ移行:
  監視くんの書き先を N(14) → M(12) に変更、K(11)=基本ポイント(¥) を amazon 行に追加。
  N は誰も書かず HQ が =(M or F)−K の ARRAYFORMULA を設置する (切替順序: Inventory deploy → HQ 関数化)。

仕様:
- price_jpy が int (>=0) で渡された行のみ M 列書込。None / 不在 / 非 int → M 列触らない (既存値維持)。
- points_jpy が int (>=0) の行のみ K 列書込 (= M を書く行に限る)。表示なし→0 / fetch 失敗→不触。
- N 列は一切書かない。
- D/O 列のロジックは一切変えない (purely additive)。
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
def test_m_k_n_col_constants_defined():
    """M(12)=現在価格 / K(11)=ポイント / N(14)=関数(read専用) 定数が定義されている."""
    from sheet_updater import (
        LISTINGS_COL_POINTS, LISTINGS_COL_PRICE_NOW_M, LISTINGS_COL_PRICE_NOW,
    )
    assert LISTINGS_COL_POINTS == 11        # K = 'ポイント(円)' (実シート確認済)
    assert LISTINGS_COL_PRICE_NOW_M == 13   # M = '現在価格(円)' (col12=L は ConditionID、書込厳禁)
    assert LISTINGS_COL_PRICE_NOW == 14     # N = '仕入れ価格（円）' 関数 (書込しない。AH 退避元 read のみ)


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
# M 列 (現在価格) 書込テスト
# ============================================================================
def test_price_jpy_writes_m_column():
    """price_jpy=int を渡すと M 列に書込される (N 列には書かない)."""
    from sheet_updater import update_listings_sold_marks
    ws = MagicMock()
    ws.batch_update = MagicMock()

    updates = [{"row_index": 5, "checked_at": "t1", "o_only": True, "price_jpy": 12480}]
    res = update_listings_sold_marks(ws, updates)

    assert res["updated"] == 1
    assert res["o_writes"] == 1
    assert res["d_writes"] == 0
    assert res["m_writes"] == 1

    args, _ = ws.batch_update.call_args
    cells = args[0]
    ranges = [c["range"] for c in cells]
    m_cell = next((c for c in cells if c["range"] == "M5"), None)
    assert m_cell is not None
    assert m_cell["values"] == [[12480]]
    assert "N5" not in ranges  # ★ N には書かない (関数化するため)


def test_price_jpy_none_skips_m_column():
    """price_jpy=None なら M 列を触らない (既存値維持)."""
    from sheet_updater import update_listings_sold_marks
    ws = MagicMock()
    ws.batch_update = MagicMock()

    updates = [{"row_index": 5, "checked_at": "t1", "o_only": True, "price_jpy": None}]
    res = update_listings_sold_marks(ws, updates)

    assert res["m_writes"] == 0
    args, _ = ws.batch_update.call_args
    assert "M5" not in [c["range"] for c in args[0]]


def test_price_jpy_absent_skips_m_column():
    """price_jpy フィールド不在なら M 列を触らない (=既存呼出側互換)."""
    from sheet_updater import update_listings_sold_marks
    ws = MagicMock()
    ws.batch_update = MagicMock()

    updates = [{"row_index": 5, "checked_at": "t1", "o_only": True}]
    res = update_listings_sold_marks(ws, updates)

    assert res["m_writes"] == 0
    args, _ = ws.batch_update.call_args
    assert "M5" not in [c["range"] for c in args[0]]


def test_price_jpy_non_int_skips_m_column():
    """非 int (str/float/bool) は M 列を触らない (型安全)."""
    from sheet_updater import update_listings_sold_marks
    ws = MagicMock()
    ws.batch_update = MagicMock()

    for bad in ["12480", 12480.5, True, False]:
        ws.reset_mock()
        updates = [{"row_index": 5, "checked_at": "t1", "o_only": True, "price_jpy": bad}]
        res = update_listings_sold_marks(ws, updates)
        assert res["m_writes"] == 0, f"bad value {bad!r} should be skipped"


def test_price_jpy_zero_writes_m_column():
    """0 円は書込 (None と区別、無料商品など想定)."""
    from sheet_updater import update_listings_sold_marks
    ws = MagicMock()
    ws.batch_update = MagicMock()

    updates = [{"row_index": 5, "checked_at": "t1", "o_only": True, "price_jpy": 0}]
    res = update_listings_sold_marks(ws, updates)
    assert res["m_writes"] == 1


def test_price_jpy_with_d_plus_o_combination():
    """変化あり (D+O) 行でも M 列書込が並行動作 (N は書かない)."""
    from sheet_updater import update_listings_sold_marks
    ws = MagicMock()
    ws.batch_update = MagicMock()

    updates = [{"row_index": 7, "is_sold": True, "checked_at": "t1", "price_jpy": 9800}]
    res = update_listings_sold_marks(ws, updates)
    assert res["d_writes"] == 1
    assert res["o_writes"] == 1
    assert res["m_writes"] == 1
    args, _ = ws.batch_update.call_args
    ranges = sorted(c["range"] for c in args[0])
    assert ranges == sorted(["D7", "O7", "M7"])


# ============================================================================
# K 列 (基本ポイント) 書込テスト
# ============================================================================
def test_points_jpy_writes_k_column():
    """points_jpy=int を渡すと K 列に書込される (M と同時)."""
    from sheet_updater import update_listings_sold_marks
    ws = MagicMock()
    ws.batch_update = MagicMock()

    updates = [{"row_index": 8, "checked_at": "t", "o_only": True,
                "price_jpy": 14085, "points_jpy": 1831}]
    res = update_listings_sold_marks(ws, updates)
    assert res["m_writes"] == 1
    assert res["k_writes"] == 1
    args, _ = ws.batch_update.call_args
    cells = args[0]
    k_cell = next((c for c in cells if c["range"] == "K8"), None)
    assert k_cell is not None
    assert k_cell["values"] == [[1831]]


def test_points_jpy_zero_writes_k_column():
    """points_jpy=0 (= ポイント表示なしの確定観測) も K 列に書込 (0 で上書き)."""
    from sheet_updater import update_listings_sold_marks
    ws = MagicMock()
    ws.batch_update = MagicMock()

    updates = [{"row_index": 8, "checked_at": "t", "o_only": True,
                "price_jpy": 5000, "points_jpy": 0}]
    res = update_listings_sold_marks(ws, updates)
    assert res["k_writes"] == 1
    args, _ = ws.batch_update.call_args
    k_cell = next((c for c in args[0] if c["range"] == "K8"), None)
    assert k_cell["values"] == [[0]]


def test_points_jpy_absent_skips_k_column():
    """points_jpy 不在 (= mercari 等 非 amazon / fetch 失敗) なら K 列を触らない (既存値維持)."""
    from sheet_updater import update_listings_sold_marks
    ws = MagicMock()
    ws.batch_update = MagicMock()

    updates = [{"row_index": 8, "checked_at": "t", "o_only": True, "price_jpy": 5000}]
    res = update_listings_sold_marks(ws, updates)
    assert res["k_writes"] == 0
    args, _ = ws.batch_update.call_args
    assert "K8" not in [c["range"] for c in args[0]]


def test_points_jpy_without_price_not_written():
    """★ K は M を書く行に限る: price_jpy=None なら points_jpy を渡しても K を書かない.
    (= fetch 失敗行に K だけ入る事故を防ぐ = 「M と K は同一フェッチで一貫更新」)."""
    from sheet_updater import update_listings_sold_marks
    ws = MagicMock()
    ws.batch_update = MagicMock()

    updates = [{"row_index": 8, "checked_at": "t", "o_only": True,
                "price_jpy": None, "points_jpy": 1831}]
    res = update_listings_sold_marks(ws, updates)
    assert res["m_writes"] == 0
    assert res["k_writes"] == 0
    args, _ = ws.batch_update.call_args
    ranges = [c["range"] for c in args[0]]
    assert "M8" not in ranges and "K8" not in ranges


def test_points_jpy_non_int_skips_k_column():
    """points_jpy が非 int なら K 列を触らない (型安全)."""
    from sheet_updater import update_listings_sold_marks
    ws = MagicMock()
    ws.batch_update = MagicMock()

    for bad in ["1831", 1831.0, True]:
        ws.reset_mock()
        updates = [{"row_index": 8, "checked_at": "t", "o_only": True,
                    "price_jpy": 5000, "points_jpy": bad}]
        res = update_listings_sold_marks(ws, updates)
        assert res["k_writes"] == 0, f"bad points {bad!r} should be skipped"


# ============================================================================
# AH 列 (前期 N) 退避
# ============================================================================
def test_ah_copies_prev_n_before_m_write():
    """M を書く行で prev_n_jpy_str (read 時の N 計算値) が AH にコピーされる."""
    from sheet_updater import update_listings_sold_marks
    ws = MagicMock()
    ws.batch_update = MagicMock()

    updates = [{"row_index": 9, "checked_at": "t", "o_only": True,
                "price_jpy": 3000, "prev_n_jpy_str": "2800"}]
    res = update_listings_sold_marks(ws, updates)
    assert res["ah_writes"] == 1
    args, _ = ws.batch_update.call_args
    ah_cell = next((c for c in args[0] if c["range"] == "AH9"), None)
    assert ah_cell is not None
    assert ah_cell["values"] == [["2800"]]


# ============================================================================
# 混在 batch / 空 / 後方互換
# ============================================================================
def test_mixed_batch_with_m_k_writes():
    """同一 batch で M/K 書込・スキップが混在しても正しく分離処理される."""
    from sheet_updater import update_listings_sold_marks
    ws = MagicMock()
    ws.batch_update = MagicMock()

    updates = [
        {"row_index": 2, "is_sold": True, "checked_at": "t", "price_jpy": 100, "points_jpy": 5},  # D+O+M+K
        {"row_index": 3, "checked_at": "t", "o_only": True, "price_jpy": 200},                    # O+M (K なし=mercari)
        {"row_index": 4, "checked_at": "t", "o_only": True},                                       # O only
        {"row_index": 5, "is_sold": False, "checked_at": "t", "price_jpy": None, "points_jpy": 9}, # D+O (price None → M/K なし)
    ]
    res = update_listings_sold_marks(ws, updates)

    assert res["updated"] == 4
    assert res["d_writes"] == 2  # row 2, 5
    assert res["o_writes"] == 4  # 全行
    assert res["m_writes"] == 2  # row 2, 3
    assert res["k_writes"] == 1  # row 2 のみ (row5 は price None で弾かれる)

    args, _ = ws.batch_update.call_args
    ranges = sorted(c["range"] for c in args[0])
    assert ranges == sorted(["D2", "O2", "M2", "K2", "O3", "M3", "O4", "D5", "O5"])


def test_empty_returns_new_write_keys_zero():
    """updates 空でも m_writes/k_writes キーが返る (n_writes は廃止)."""
    from sheet_updater import update_listings_sold_marks
    ws = MagicMock()
    res = update_listings_sold_marks(ws, [])
    assert res == {"updated": 0, "d_writes": 0, "o_writes": 0, "m_writes": 0, "k_writes": 0,
                   "ah_writes": 0, "err_writes": 0}


def test_legacy_call_without_price_jpy_unchanged():
    """price_jpy 無し呼出は従来通り D+O のみ (既存呼出側互換、M/N/K に副作用なし)."""
    from sheet_updater import update_listings_sold_marks
    ws = MagicMock()
    ws.batch_update = MagicMock()

    updates = [{"row_index": 7, "is_sold": True, "checked_at": "t1"}]
    res = update_listings_sold_marks(ws, updates)

    assert res["d_writes"] == 1
    assert res["o_writes"] == 1
    assert res["m_writes"] == 0
    assert res["k_writes"] == 0

    args, _ = ws.batch_update.call_args
    ranges = [c["range"] for c in args[0]]
    assert "D7" in ranges
    assert "O7" in ranges
    assert "M7" not in ranges and "N7" not in ranges and "K7" not in ranges


# ============================================================================
# monitor_listings が price_jpy / points_jpy を result に含めるか
# ============================================================================
def test_check_one_row_includes_price_jpy_field():
    """check_one_row の戻り値に price_jpy フィールドが含まれる (mercari は points_jpy=None)."""
    import monitor_listings as ml

    fake_info = {"name": "test", "status": "ON_SALE",
                 "skus": [{"in_stock": True, "price_jpy": 12480}]}
    orig = ml.fetch_mercari
    try:
        ml.fetch_mercari = lambda url, driver=None, use_selenium_fallback=False: fake_info
        row = {"row_index": 10, "url": "https://jp.mercari.com/item/m12345",
               "item_id": "999", "title": "test", "current_sold": ""}
        result = ml.check_one_row(row, sleep_sec=0)
    finally:
        ml.fetch_mercari = orig

    assert result["price_jpy"] == 12480
    assert result["is_sold"] is False
    assert result.get("points_jpy") is None  # mercari はポイントなし


def test_check_one_row_price_jpy_none_when_scraper_returns_none():
    """scraper が None を返した場合は price_jpy=None / points_jpy=None (M/K 維持仕様)."""
    import monitor_listings as ml
    orig = ml.fetch_mercari
    try:
        ml.fetch_mercari = lambda url, driver=None, use_selenium_fallback=False: None
        row = {"row_index": 10, "url": "https://jp.mercari.com/item/m12345",
               "item_id": "999", "title": "test", "current_sold": ""}
        result = ml.check_one_row(row, sleep_sec=0)
    finally:
        ml.fetch_mercari = orig

    assert result["price_jpy"] is None
    assert result.get("points_jpy") is None
    assert result["error"] == "scraper returned None (fail-closed)"


def test_check_one_row_carries_amazon_points_jpy():
    """amazon 在庫あり行は skus[0].points_jpy を result.points_jpy まで運ぶ."""
    import monitor_listings as ml
    fake_info = {"name": "gshock", "status": "in_stock",
                 "skus": [{"in_stock": True, "price_jpy": 14085, "points_jpy": 1831}]}
    orig = ml.fetch_amazon
    try:
        ml.fetch_amazon = lambda url, driver=None, use_selenium_fallback=True: fake_info
        row = {"row_index": 20, "url": "https://www.amazon.co.jp/dp/B000TEST00",
               "item_id": "111", "title": "gshock", "current_sold": ""}
        result = ml.check_one_row(row, sleep_sec=0)
    finally:
        ml.fetch_amazon = orig

    assert result["price_jpy"] == 14085
    assert result["points_jpy"] == 1831
    assert result["is_sold"] is False


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
