"""補URL救済ログ (フック2) の regression test.

★ 2026-07-25 HQ 実装go (Phase1 救済率 signal)。
救済 = 主URL(A) is_sold=True 確定 (取得成功) AND 補URL≥1本 in_stock 確定。
- fail-closed: 主が None/error(uncertain) は救済にカウントしない (数字を過大にしない)。
- 通常在庫 (主生存) は救済でない。
- 遷移ベース dedup: 救済状態への遷移を1回記録 (延べ cycle 水増し防止)、復活→再死は再カウント。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _mk_row(rowidx=5, slots=None):
    return {"row_index": rowidx, "url": "https://main", "item_id": "ITEM%d" % rowidx,
            "title": "PSA10 X", "current_sold": "",
            "backup_url_slots": slots or [None, "https://b2", None, None, None]}


def _patch_scrape(monkeypatch, table):
    import monitor_listings as ml

    def fake_check(url, *a, **k):
        return {"url": url, "supplier": "amazon", "is_sold": table.get(url),
                "raw_status": "os" if table.get(url) else "in", "error": None,
                "price_jpy": None, "points_jpy": None}
    monkeypatch.setattr(ml, "_check_single_url", fake_check)
    return ml


# ============================================================================
# 救済 signal (fail-closed)
# ============================================================================
def test_rescue_true_when_main_sold_and_backup_instock(monkeypatch):
    """主 売切確定 + 補 在庫 → rescued=True + detail."""
    ml = _patch_scrape(monkeypatch, {"https://main": True, "https://b2": False})
    res = ml.check_one_row_with_fallback(_mk_row())
    assert res["rescued"] is True
    assert res["is_sold"] is False   # 補で延命 → 取下げない
    assert res["rescue_detail"]["backup_slot"] == 1     # AD
    assert res["rescue_detail"]["backup_url"] == "https://b2"


def test_rescue_false_when_main_uncertain(monkeypatch):
    """★fail-closed: 主が取得失敗(None) なら補が在庫でも救済に数えない."""
    ml = _patch_scrape(monkeypatch, {"https://main": None, "https://b2": False})
    res = ml.check_one_row_with_fallback(_mk_row())
    assert res["rescued"] is False


def test_rescue_false_when_main_in_stock(monkeypatch):
    """通常在庫 (主生存) は救済でない."""
    ml = _patch_scrape(monkeypatch, {"https://main": False, "https://b2": False})
    res = ml.check_one_row_with_fallback(_mk_row())
    assert res["rescued"] is False


def test_rescue_false_when_all_sold(monkeypatch):
    """主も補も全売切 → 救済でない (取下げ対象)."""
    ml = _patch_scrape(monkeypatch, {"https://main": True, "https://b2": True})
    res = ml.check_one_row_with_fallback(_mk_row())
    assert res["rescued"] is False
    assert res["is_sold"] is True


def test_rescue_false_when_backup_errored(monkeypatch):
    """主 売切 + 補が error(None) → in_stock 確定でないので救済でない (fail-closed)."""
    ml = _patch_scrape(monkeypatch, {"https://main": True, "https://b2": None})
    res = ml.check_one_row_with_fallback(_mk_row())
    assert res["rescued"] is False


# ============================================================================
# 遷移ベース dedup (state)
# ============================================================================
def test_rescue_state_roundtrip(monkeypatch, tmp_path):
    import monitor_listings as ml
    monkeypatch.setattr(ml, "DECISION_LOG_DIR", tmp_path)
    assert ml.load_rescue_state("HIGH") == set()
    ml.save_rescue_state("HIGH", {"ITEM5", "ITEM7"})
    assert ml.load_rescue_state("HIGH") == {"ITEM5", "ITEM7"}


def test_rescue_key_prefers_item_id():
    import monitor_listings as ml
    assert ml._rescue_key({"item_id": "ABC", "row_index": 5}) == "ABC"
    assert ml._rescue_key({"item_id": "", "row_index": 5}) == "row:5"


# ============================================================================
# append_rescue_log_rows (explicit range, not append_rows)
# ============================================================================
def test_append_rescue_log_creates_tab_and_appends():
    from sheet_updater import append_rescue_log_rows, RESCUE_LOG_TAB, RESCUE_LOG_HEADER
    import gspread
    sh = MagicMock()
    ws_log = MagicMock()
    # タブ無し → add_worksheet 経路
    sh.worksheet = MagicMock(side_effect=gspread.WorksheetNotFound("x"))
    sh.add_worksheet = MagicMock(return_value=ws_log)
    ws_log.col_values = MagicMock(return_value=[RESCUE_LOG_HEADER[0]])  # header のみ
    ws_log.update = MagicMock()
    events = [{"date": "2026/07/25", "item_id": "IT1", "title": "T",
               "backup_slot": "AD", "main_status": "all_sold", "backup_url": "https://b"}]
    res = append_rescue_log_rows(sh, events)
    assert res["appended"] == 1
    assert res["tab"] == RESCUE_LOG_TAB
    # 明示 range で next_row=2 に書く (append_rows は使わない)
    call = ws_log.update.call_args
    assert "A2:F2" in (call.kwargs.get("range_name") or "")


def test_append_rescue_log_empty_noop():
    from sheet_updater import append_rescue_log_rows
    sh = MagicMock()
    res = append_rescue_log_rows(sh, [])
    assert res["appended"] == 0
    sh.worksheet.assert_not_called()
