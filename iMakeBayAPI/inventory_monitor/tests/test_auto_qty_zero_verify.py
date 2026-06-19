"""auto_qty_zero の取下げ後 実eBay verify regression (2026-06-19).

bug: update_sku_sheet_after_success が K に目標値(0)を楽観的に書き対処済を無条件で立てた
→ eBay に取下げが届かなくても K=0/対処済 になり silent fail-OPEN (montbell M 5件 実害)。
修正: 取下げ後 GetItem で実 qty 再確認、 実 qty==目標 のみ対処済、 未反映/未確認は対処要のまま
+ unresolved に収集 (silent化しない)。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import auto_qty_zero as A  # noqa: E402


class _FakeWS:
    def __init__(self):
        self.updates = None

    def batch_update(self, cell_updates, value_input_option=None):
        self.updates = cell_updates


def _ranges(ws):
    return {u["range"] for u in (ws.updates or [])}


def test_verified_zero_marks_done(monkeypatch):
    ws = _FakeWS()
    monkeypatch.setattr(A, "get_sku_worksheet", lambda sh: ws)
    monkeypatch.setattr(A, "_actual_ebay_qty_by_sku", lambda ids: {"L1": {"skuA": 0}})
    applied = [{"row_index": 5, "listing_id": "L1", "sku_id": "skuA", "size": "M", "color": "BK"}]
    n, unres = A.update_sku_sheet_after_success(None, applied, "2026/06/19", new_qty=0)
    r = _ranges(ws)
    assert {"A5", "B5", "C5", "K5"} <= r  # 対処済 + K
    assert unres == []


def test_still_live_not_marked_and_unresolved(monkeypatch):
    """eBay 実 qty=1 (取下げ未反映) → 対処済にせず、 K=実値、 unresolved に。"""
    ws = _FakeWS()
    monkeypatch.setattr(A, "get_sku_worksheet", lambda sh: ws)
    monkeypatch.setattr(A, "_actual_ebay_qty_by_sku", lambda ids: {"L1": {"skuA": 1}})
    applied = [{"row_index": 5, "listing_id": "L1", "sku_id": "skuA", "size": "M", "color": "BK"}]
    n, unres = A.update_sku_sheet_after_success(None, applied, "ts", new_qty=0)
    r = _ranges(ws)
    assert "A5" not in r and "B5" not in r  # 対処済にしない (= 対処要のまま)
    assert "K5" in r  # K に実値(1)反映
    assert len(unres) == 1 and unres[0]["actual_qty"] == 1


def test_getitem_fail_unresolved_no_write(monkeypatch):
    """GetItem 失敗 (確認不能) → 触らず対処要のまま、 unresolved に (silent化しない)。"""
    ws = _FakeWS()
    monkeypatch.setattr(A, "get_sku_worksheet", lambda sh: ws)
    monkeypatch.setattr(A, "_actual_ebay_qty_by_sku", lambda ids: {"L1": None})
    applied = [{"row_index": 5, "listing_id": "L1", "sku_id": "skuA"}]
    n, unres = A.update_sku_sheet_after_success(None, applied, "ts", new_qty=0)
    assert not ws.updates  # 何も書かない
    assert len(unres) == 1 and unres[0]["actual_qty"] == "unknown"


def test_ended_listing_treated_as_zero(monkeypatch):
    """listing ended (= GetItem err17) → qty=0 同等 = 対処済。"""
    ws = _FakeWS()
    monkeypatch.setattr(A, "get_sku_worksheet", lambda sh: ws)
    monkeypatch.setattr(A, "_actual_ebay_qty_by_sku", lambda ids: {"L1": "ended"})
    applied = [{"row_index": 7, "listing_id": "L1", "sku_id": "skuA"}]
    n, unres = A.update_sku_sheet_after_success(None, applied, "ts", new_qty=0)
    assert {"A7", "B7", "K7"} <= _ranges(ws)
    assert unres == []


def test_restore_verified_one_marks_done(monkeypatch):
    """復活 (new_qty=1): 実 qty=1 確認 → 対処済。"""
    ws = _FakeWS()
    monkeypatch.setattr(A, "get_sku_worksheet", lambda sh: ws)
    monkeypatch.setattr(A, "_actual_ebay_qty_by_sku", lambda ids: {"L1": {"skuA": 1}})
    applied = [{"row_index": 9, "listing_id": "L1", "sku_id": "skuA"}]
    n, unres = A.update_sku_sheet_after_success(None, applied, "ts", new_qty=1)
    assert {"A9", "B9", "K9"} <= _ranges(ws)
    assert unres == []
