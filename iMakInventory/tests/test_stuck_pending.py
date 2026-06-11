"""滞留 pending 検知 (get_stuck_pending_items) の offline テスト.

2026-06-11: network 失敗等で複数 cycle 取下げ失敗継続する item が pending に silent
滞留する事故 (G-SHOCK 356901158380 が約19h無通知) の再発防止ガード。
"""
from datetime import datetime

import pytest

import ebay_actions.revise_csv_generator as rg

pytestmark = pytest.mark.offline

_NOW = datetime(2026, 6, 11, 12, 0, 0)


def _entries():
    return [
        {"ts": "2026-06-10T16:46:00", "item_id": "OLD1", "sheet": "LOW", "row_index": 214,
         "url": "u1", "supplier": "amazon"},                       # ~19h → 滞留
        {"ts": "2026-06-11T02:00:00", "item_id": "MID1", "sheet": "HIGH", "row_index": 5,
         "url": "u2", "supplier": "mercari"},                       # 10h → 滞留
        {"ts": "2026-06-11T07:00:00", "item_id": "NEW1", "sheet": "HIGH", "row_index": 9,
         "url": "u3", "supplier": "mercari"},                       # 5h → 滞留でない
        {"ts": "bad-ts", "item_id": "BAD", "sheet": "X"},          # parse 不能 → 無視
    ]


def test_stuck_detects_only_aged(monkeypatch):
    monkeypatch.setattr(rg, "read_pending_queue", _entries)
    stuck = rg.get_stuck_pending_items(threshold_hours=8.0, now=_NOW)
    ids = [s["item_id"] for s in stuck]
    assert ids == ["OLD1", "MID1"]           # 古い順、 5h の NEW1 と parse 不能 BAD は除外
    assert stuck[0]["age_hours"] >= 19.0
    assert "age_hours" in stuck[1]


def test_stuck_empty_when_all_fresh(monkeypatch):
    monkeypatch.setattr(rg, "read_pending_queue", lambda: [
        {"ts": _NOW.isoformat(), "item_id": "FRESH", "sheet": "HIGH"},
    ])
    assert rg.get_stuck_pending_items(threshold_hours=8.0, now=_NOW) == []


def test_stuck_empty_queue(monkeypatch):
    monkeypatch.setattr(rg, "read_pending_queue", lambda: [])
    assert rg.get_stuck_pending_items(now=_NOW) == []
