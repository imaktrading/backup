"""持続エラーの「墓場化」対策: ×8 以上を「死んだ仕入元」として別枠化 (2026-07-28 HQ 指摘).

持続エラーは ×3 で「要手動 chk」に上がるが、そこから降りる経路が自己回復しかないため、
回復しない URL (出品終了・削除済 等) が ×4 → ×10 → ×20 と単調に育ち要対応リストが墓場になる
(安全原則3: DLQ を墓場にしない)。件数を消すのではなく「必要な対処 = URL 差替」に分類し直す。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

pytestmark = pytest.mark.offline


# ---------------------------------------------------------------- 閾値判定
def test_thresholds():
    import err_flag as ef
    assert ef.PERSISTENT_THRESHOLD == 3 and ef.DEAD_SOURCE_THRESHOLD == 8
    assert ef.is_persistent("⚠ scraper ×3 07/28 10:00") is True
    assert ef.is_dead_source("⚠ scraper ×7 07/28 10:00") is False
    assert ef.is_dead_source("⚠ scraper ×8 07/28 10:00") is True
    assert ef.is_dead_source("") is False


def test_marker_keeps_counting_after_dead():
    """死んだ扱いにしても計数は続ける (= 消さない・silent drop しない)"""
    import err_flag as ef
    m = ef.build_err_marker("scraper returned None", "⚠ scraper ×9 07/28 10:00")
    assert ef.marker_count(m) == 10 and ef.is_dead_source(m)


# ---------------------------------------------------------------- 振り分け
def _row(idx, count, item_id="123", sold=""):
    return {"row_index": idx, "item_id": item_id, "url": f"https://x/{idx}", "title": "t",
            "count": count, "error": "scraper returned None (fail-closed)", "supplier": "amazon",
            "current_sold": sold}


def _split(rows):
    """monitor_listings の振り分けロジックと同じ条件を再現して検証する"""
    from err_flag import PERSISTENT_THRESHOLD, DEAD_SOURCE_THRESHOLD
    persistent, dead = [], []
    for r in rows:
        if r["count"] < PERSISTENT_THRESHOLD:
            continue
        iid = (r["item_id"] or "").strip()
        e = {**r, "listing_risk": bool(iid and iid != "9999" and not r["current_sold"].strip())}
        (dead if r["count"] >= DEAD_SOURCE_THRESHOLD else persistent).append(e)
    return persistent, dead


def test_split_moves_only_dead_rows():
    persistent, dead = _split([_row(1, 2), _row(2, 3), _row(3, 7), _row(4, 8), _row(5, 20)])
    assert [r["row_index"] for r in persistent] == [2, 3]
    assert [r["row_index"] for r in dead] == [4, 5]


def test_listing_risk_flag():
    """出品が生きている行 (item_id あり × D≠○) だけが在庫不明の実リスク"""
    _, dead = _split([_row(1, 9), _row(2, 9, sold="○"), _row(3, 9, item_id=""), _row(4, 9, item_id="9999")])
    risk = {r["row_index"]: r["listing_risk"] for r in dead}
    assert risk == {1: True, 2: False, 3: False, 4: False}


# ---------------------------------------------------------------- メール描画
def test_email_renders_dead_block_separately():
    import email_notifier as en
    cycle_log = {
        "ts_start": "2026-07-28T22:45:00", "status": "success", "sheet": "low",
        "phases": {"monitor": {
            "processed": 100, "newly_sold": 0, "newly_in_stock": 0, "errors": 2,
            "error_rows": [], "by_sheet": {},
            "persistent_err_rows": [{"sheet": "LOW", "row_index": 10, "count": 4,
                                     "item_id": "1", "url": "https://a", "supplier": "amazon",
                                     "listing_risk": True}],
            "dead_source_rows": [{"sheet": "LOW", "row_index": 20, "count": 9,
                                  "item_id": "2", "url": "https://b", "supplier": "amazon",
                                  "listing_risk": True},
                                 {"sheet": "LOW", "row_index": 21, "count": 12,
                                  "item_id": "", "url": "https://c", "supplier": "amazon",
                                  "listing_risk": False}],
        }, "action_required_summary": {"count": 0, "items": []}},
    }
    body = en._format_body(cycle_log)
    assert "死んだ仕入元 2 件" in body
    assert "出品が生きている行 = 1 件" in body      # 優先対処の内訳が出る
    assert "row20" in body and "row21" in body      # 消さずに全部見える
    assert "持続エラー 1 件" in body                 # 回復待ち枠は別に残る
