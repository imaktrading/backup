"""補仕入URL fallback (短絡評価) の regression test.

依頼: HQ requests/2026-05-10_multi_sourcing_url_fallback.md
- 主 URL + 補 URL 1〜5 の計 6 候補を順にチェック
- 1 件でも在庫あり → 取下げ skip (短絡で残り skip)
- 全候補 sold + error 無し → newly_sold
- error 含むと不確定 (Precision 100%、取下げ skip)
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ============================================================================
# fixtures: scrapers を mock するヘルパ
# ============================================================================
def _stub_check_single_url(in_stock_per_url: dict):
    """`_check_single_url` を mock する factory.

    Args:
        in_stock_per_url: { url -> "in_stock" | "sold" | "error" }
    """
    def _stub(url, sleep_sec=0, mercari_driver=None, amazon_driver=None):
        v = in_stock_per_url.get(url, "sold")
        if v == "in_stock":
            return {"url": url, "supplier": "mercari", "is_sold": False,
                    "raw_status": "in_stock", "error": None, "price_jpy": 1500}
        elif v == "sold":
            return {"url": url, "supplier": "mercari", "is_sold": True,
                    "raw_status": "out_of_stock", "error": None, "price_jpy": None}
        elif v == "error":
            return {"url": url, "supplier": "mercari", "is_sold": None,
                    "raw_status": "", "error": "scraper returned None (fail-closed)",
                    "price_jpy": None}
        else:
            raise ValueError(f"unknown stub state: {v}")
    return _stub


def _row(main_url, backup_urls=(), current_sold=""):
    return {"row_index": 100, "url": main_url, "item_id": "356xxx",
            "title": "test row", "current_sold": current_sold,
            "backup_urls": list(backup_urls)}


# ============================================================================
# 短絡評価の core ロジック
# ============================================================================
def test_main_in_stock_all_candidates_checked():
    """主 URL 在庫あり → 在庫あり判定。短絡解除済 (B 案) なので補も全部 scrape する."""
    from monitor_listings import check_one_row_with_fallback
    stub = _stub_check_single_url({"main": "in_stock", "b1": "sold", "b2": "sold"})
    with patch("monitor_listings._check_single_url", side_effect=stub) as mock:
        res = check_one_row_with_fallback(_row("main", ["b1", "b2"]))
    assert res["is_sold"] is False
    assert res["error"] is None
    assert res["candidates_checked"] == 3   # 主 + 補1 + 補2 全部チェック
    assert res["raw_status"] == "in_stock"
    assert mock.call_count == 3


def test_main_sold_backup_in_stock_returns_in_stock():
    """主売切 + 補1在庫あり → in_stock 確定。補2 もチェックされる (色塗り用)."""
    from monitor_listings import check_one_row_with_fallback
    stub = _stub_check_single_url({"main": "sold", "b1": "in_stock", "b2": "sold"})
    with patch("monitor_listings._check_single_url", side_effect=stub) as mock:
        res = check_one_row_with_fallback(_row("main", ["b1", "b2"]))
    assert res["is_sold"] is False
    assert res["error"] is None
    assert "backup#1" in res["raw_status"]
    assert res["candidates_checked"] == 3   # 全候補チェック
    assert mock.call_count == 3


def test_all_candidates_sold_returns_newly_sold():
    """全候補売切 (error 無し) → is_sold=True で newly_sold 判定."""
    from monitor_listings import check_one_row_with_fallback
    stub = _stub_check_single_url({"main": "sold", "b1": "sold", "b2": "sold"})
    with patch("monitor_listings._check_single_url", side_effect=stub):
        res = check_one_row_with_fallback(_row("main", ["b1", "b2"], current_sold=""))
    assert res["is_sold"] is True
    assert res["error"] is None
    assert res["delta"] == "newly_sold"
    assert "all_sold (3/3)" in res["raw_status"]
    assert res["candidates_checked"] == 3


def test_partial_error_yields_uncertain_not_sold():
    """主売切 + 補1 error + 補2売切 → 不確定 (= 取下げ skip、Precision 100%)."""
    from monitor_listings import check_one_row_with_fallback
    stub = _stub_check_single_url({"main": "sold", "b1": "error", "b2": "sold"})
    with patch("monitor_listings._check_single_url", side_effect=stub):
        res = check_one_row_with_fallback(_row("main", ["b1", "b2"]))
    assert res["is_sold"] is None   # 不確定
    assert res["error"] is not None
    assert "uncertain" in res["error"]
    assert "1/3" in res["error"]   # 1 件 error / 3 候補
    assert res["delta"] == "uncertain"


def test_main_error_with_backup_in_stock_returns_in_stock_safe():
    """主 error + 補1 在庫あり → in_stock 確定 (主の error は無視)、補2 もチェック."""
    from monitor_listings import check_one_row_with_fallback
    stub = _stub_check_single_url({"main": "error", "b1": "in_stock", "b2": "sold"})
    with patch("monitor_listings._check_single_url", side_effect=stub) as mock:
        res = check_one_row_with_fallback(_row("main", ["b1", "b2"]))
    assert res["is_sold"] is False
    assert res["error"] is None
    assert "backup#1" in res["raw_status"]
    assert mock.call_count == 3   # 全候補チェック


def test_all_errors_yields_uncertain():
    """全候補 error → 不確定 (取下げ skip、Defect Rate 防止)."""
    from monitor_listings import check_one_row_with_fallback
    stub = _stub_check_single_url({"main": "error", "b1": "error"})
    with patch("monitor_listings._check_single_url", side_effect=stub):
        res = check_one_row_with_fallback(_row("main", ["b1"]))
    assert res["is_sold"] is None
    assert res["error"] is not None
    assert "uncertain" in res["error"]
    assert "2/2" in res["error"]


def test_no_backup_urls_behaves_like_check_one_row():
    """backup_urls 空 → 既存挙動と完全等価 (後方互換)."""
    from monitor_listings import check_one_row_with_fallback
    stub = _stub_check_single_url({"main": "sold"})
    with patch("monitor_listings._check_single_url", side_effect=stub) as mock:
        res = check_one_row_with_fallback(_row("main", []))
    assert res["is_sold"] is True
    assert res["candidates_checked"] == 1
    assert mock.call_count == 1
    # 単一候補時は raw_status を helper の値そのまま使う (all_sold (1/1) ではなく)
    assert res["raw_status"] == "out_of_stock"


def test_delta_newly_in_stock_when_main_returns_to_stock():
    """主が再入荷 (D 列既に ○、現在は in_stock) → newly_in_stock."""
    from monitor_listings import check_one_row_with_fallback
    stub = _stub_check_single_url({"main": "in_stock"})
    with patch("monitor_listings._check_single_url", side_effect=stub):
        res = check_one_row_with_fallback(_row("main", [], current_sold="○"))
    assert res["is_sold"] is False
    assert res["delta"] == "newly_in_stock"


def test_check_one_row_unchanged_for_backward_compat():
    """既存 check_one_row API も backup_urls 無視で動く (= 既存呼び出し全部維持)."""
    from monitor_listings import check_one_row
    stub = _stub_check_single_url({"main": "sold"})
    with patch("monitor_listings._check_single_url", side_effect=stub):
        # backup_urls フィールドを含む row を渡しても、check_one_row は無視
        res = check_one_row({"row_index": 1, "url": "main", "item_id": "x",
                              "title": "t", "current_sold": "",
                              "backup_urls": ["b1", "b2"]})
    assert res["is_sold"] is True
    assert "candidates_checked" in res
    assert res["candidates_checked"] == 1   # check_one_row は短絡なしの単一呼出


# ============================================================================
# read_listings_rows: backup_urls フィールドが入る
# ============================================================================
def test_read_listings_rows_extracts_backup_urls():
    """read_listings_rows が AC-AG (#29-33) を backup_urls に組み立てる."""
    from sheet_updater import read_listings_rows

    class FakeWS:
        def get_all_values(self):
            # row 1: header (ignored), row 2: data row
            empty = [""] * 34
            row1 = empty[:]
            row2 = empty[:]
            row2[0] = "https://main.example/x"
            row2[1] = "356"
            row2[2] = "title"
            row2[3] = ""           # D 列空
            row2[13] = "1500"      # N 列 (現在 N) → list index 13
            row2[14] = "2026/01/01"
            # AC-AG (#29-33) → list index 28-32
            row2[28] = "https://b1.example/x"
            row2[29] = ""           # 空欄は除外される
            row2[30] = "https://b3.example/x"
            row2[31] = ""
            row2[32] = "https://b5.example/x"
            return [row1, row2]

    rows = read_listings_rows(FakeWS(), start_row=2)
    assert len(rows) == 1
    r = rows[0]
    assert r["url"] == "https://main.example/x"
    assert r["backup_urls"] == [
        "https://b1.example/x",
        "https://b3.example/x",
        "https://b5.example/x",
    ]
    assert r["current_n_jpy_str"] == "1500"


# ============================================================================
# AH 列 (前期 N) 書込テスト: update_listings_sold_marks
# ============================================================================
class _FakeWS:
    """update_listings_sold_marks 用の最小 mock."""
    def __init__(self):
        self.batch_calls = []

    def batch_update(self, updates, value_input_option=None):
        self.batch_calls.append(list(updates))


def test_ah_written_when_n_is_updated():
    """N 列を更新する時、AH に旧 N (prev_n_jpy_str) もコピーされる."""
    from sheet_updater import update_listings_sold_marks
    ws = _FakeWS()
    res = update_listings_sold_marks(ws, [{
        "row_index":       100,
        "is_sold":         False,
        "checked_at":      "2026/05/10 10:00:00",
        "price_jpy":       3000,           # 新 N
        "prev_n_jpy_str":  "1500",         # 旧 N (= AH に書く)
    }])
    assert res["n_writes"] == 1
    assert res["ah_writes"] == 1
    # 1 batch_update 内に AH と N が両方含まれる
    cells = ws.batch_calls[0]
    ranges = {c["range"]: c["values"][0][0] for c in cells}
    assert ranges.get("AH100") == "1500"
    assert ranges.get("N100") == 3000


def test_ah_not_written_when_prev_n_empty():
    """初回 cycle (= AH に書く前期 N が無い) は AH に touch しない."""
    from sheet_updater import update_listings_sold_marks
    ws = _FakeWS()
    res = update_listings_sold_marks(ws, [{
        "row_index":       100,
        "is_sold":         False,
        "checked_at":      "2026/05/10 10:00:00",
        "price_jpy":       3000,
        "prev_n_jpy_str":  "",     # 旧 N が空
    }])
    assert res["n_writes"] == 1
    assert res["ah_writes"] == 0
    cells = ws.batch_calls[0]
    ranges = [c["range"] for c in cells]
    assert "AH100" not in ranges
    assert "N100" in ranges


def test_ah_not_written_when_n_skipped():
    """price_jpy=None (scrape 失敗) で N も AH も touch しない."""
    from sheet_updater import update_listings_sold_marks
    ws = _FakeWS()
    res = update_listings_sold_marks(ws, [{
        "row_index":       100,
        "checked_at":      "2026/05/10 10:00:00",
        "o_only":          True,
        # price_jpy なし → N も AH も触らない
    }])
    assert res["n_writes"] == 0
    assert res["ah_writes"] == 0
    cells = ws.batch_calls[0]
    ranges = [c["range"] for c in cells]
    assert "AH100" not in ranges
    assert "N100" not in ranges


def test_check_one_row_with_fallback_propagates_current_n():
    """row dict の current_n_jpy_str が result まで引き継がれる."""
    from monitor_listings import check_one_row_with_fallback
    stub = _stub_check_single_url({"main": "in_stock"})
    row = {
        "row_index": 100, "url": "main", "item_id": "356", "title": "t",
        "current_sold": "", "backup_urls": [],
        "current_n_jpy_str": "1500",
    }
    with patch("monitor_listings._check_single_url", side_effect=stub):
        res = check_one_row_with_fallback(row)
    assert res["current_n_jpy_str"] == "1500"


def test_check_one_row_with_fallback_returns_sub_results():
    """色塗り用に sub_results が result に含まれる (各候補の状態 list)."""
    from monitor_listings import check_one_row_with_fallback
    stub = _stub_check_single_url({"main": "in_stock", "b1": "sold", "b2": "error"})
    with patch("monitor_listings._check_single_url", side_effect=stub):
        res = check_one_row_with_fallback(_row("main", ["b1", "b2"]))
    sub = res.get("sub_results")
    assert sub is not None
    assert len(sub) == 3
    assert sub[0]["is_sold"] is False     # 主 in_stock
    assert sub[1]["is_sold"] is True      # 補1 sold
    assert sub[2]["error"] is not None     # 補2 error


# ============================================================================
# paint_backup_url_cells: AC-AG セル色塗り API
# ============================================================================
class _FakeWSWithSpreadsheet:
    """paint_backup_url_cells 用 mock。spreadsheet.batch_update をキャプチャ."""
    def __init__(self):
        self.id = 851100680
        self.spreadsheet = self
        self.batch_calls = []

    def batch_update(self, body):
        self.batch_calls.append(body)


def test_paint_sold_cell_red():
    """sold 状態のセルは red (1.0, 0, 0) で塗る."""
    from sheet_updater import paint_backup_url_cells
    ws = _FakeWSWithSpreadsheet()
    res = paint_backup_url_cells(ws, [{
        "row_index": 100,
        "states": ["sold", "in_stock", "error", "unknown", "unknown"],
    }])
    assert res["painted"] == 1
    assert res["red_cells"] == 1
    assert res["default_cells"] == 4
    reqs = ws.batch_calls[0]["requests"]
    assert len(reqs) == 5   # AC-AG の 5 セル
    # 最初 (AC = sold) は赤
    fmt0 = reqs[0]["repeatCell"]["cell"]["userEnteredFormat"]["textFormat"]["foregroundColor"]
    assert fmt0 == {"red": 1.0, "green": 0.0, "blue": 0.0}
    # 2 番目 (AD = in_stock) は黒
    fmt1 = reqs[1]["repeatCell"]["cell"]["userEnteredFormat"]["textFormat"]["foregroundColor"]
    assert fmt1 == {"red": 0.0, "green": 0.0, "blue": 0.0}


def test_paint_empty_states_treats_as_unknown():
    """states が短い場合、不足分は unknown 扱い (= 黒字)."""
    from sheet_updater import paint_backup_url_cells
    ws = _FakeWSWithSpreadsheet()
    res = paint_backup_url_cells(ws, [{
        "row_index": 100,
        "states": ["sold"],   # 1 件のみ、残り 4 件は unknown
    }])
    assert res["red_cells"] == 1
    assert res["default_cells"] == 4


def test_paint_no_paints_returns_zero():
    """空 list → API 呼ばれず 0 返却."""
    from sheet_updater import paint_backup_url_cells
    ws = _FakeWSWithSpreadsheet()
    res = paint_backup_url_cells(ws, [])
    assert res == {"painted": 0, "red_cells": 0, "default_cells": 0}
    assert ws.batch_calls == []


def test_paint_targets_correct_columns():
    """各補 URL のセルが AC-AG (column index 28-32, 0-based) に対応."""
    from sheet_updater import paint_backup_url_cells
    ws = _FakeWSWithSpreadsheet()
    paint_backup_url_cells(ws, [{
        "row_index": 100,
        "states": ["sold", "sold", "sold", "sold", "sold"],
    }])
    reqs = ws.batch_calls[0]["requests"]
    cols = [r["repeatCell"]["range"]["startColumnIndex"] for r in reqs]
    assert cols == [28, 29, 30, 31, 32]   # AC, AD, AE, AF, AG
