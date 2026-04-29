"""Phase 7 unit test (precheck + audit + listing_verifier).

Selenium / network を呼ぶ部分はスキップ、helpers のみ pytest 化。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ============================================================================
# 7a: pytest precheck 関連
# ============================================================================
def test_run_cycle_has_precheck_phase():
    """run_cycle._phase_pytest_precheck 関数が存在する."""
    import run_cycle
    assert hasattr(run_cycle, "_phase_pytest_precheck")
    assert callable(run_cycle._phase_pytest_precheck)


def test_pytest_ini_has_offline_marker():
    """pytest.ini に offline / live marker が登録されている."""
    pytest_ini = ROOT / "pytest.ini"
    assert pytest_ini.exists()
    content = pytest_ini.read_text(encoding="utf-8")
    assert "offline:" in content
    assert "live:" in content


# ============================================================================
# 7d': audit
# ============================================================================
def test_audit_imports():
    """audit module が import 可能."""
    import audit
    assert callable(audit.sample_and_append)
    assert callable(audit.collect_in_stock_from_log)
    assert callable(audit.find_latest_listings_log)
    assert audit.AUDIT_TAB_NAME == "audit"
    assert "cycle_ts" in audit.AUDIT_HEADERS


def test_audit_collect_in_stock_from_log(tmp_path):
    """jsonl を読んで in_stock のみ抽出."""
    from audit import collect_in_stock_from_log
    log = tmp_path / "listings_TEST_20260430.jsonl"
    rows = [
        # in_stock 2 件
        {"row_index": 1, "item_id": "111", "is_sold": False, "url": "u1",
         "title": "t1", "supplier": "mercari", "raw_status": "ON_SALE", "error": None},
        {"row_index": 2, "item_id": "222", "is_sold": False, "url": "u2",
         "title": "t2", "supplier": "amazon", "raw_status": "in_stock", "error": None},
        # sold 1 件 (除外)
        {"row_index": 3, "item_id": "333", "is_sold": True, "url": "u3",
         "title": "t3", "supplier": "mercari", "raw_status": "SOLD_OUT", "error": None},
        # error 1 件 (除外)
        {"row_index": 4, "item_id": "444", "is_sold": None, "url": "u4",
         "title": "t4", "supplier": "amazon", "raw_status": "", "error": "fail"},
    ]
    with open(log, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")

    items = collect_in_stock_from_log(log)
    assert len(items) == 2
    assert {i["item_id"] for i in items} == {"111", "222"}


def test_audit_find_latest_listings_log(tmp_path):
    """find_latest_listings_log が最新 mtime ファイルを返す."""
    from audit import find_latest_listings_log
    # 古い + 新しい
    old = tmp_path / "listings_TEST_20260101_120000.jsonl"
    new = tmp_path / "listings_TEST_20260430_120000.jsonl"
    old.write_text("{}\n", encoding="utf-8")
    time.sleep(0.05)
    new.write_text("{}\n", encoding="utf-8")
    # 別ラベル (除外されるべき)
    other = tmp_path / "listings_OTHER_20260430_120000.jsonl"
    other.write_text("{}\n", encoding="utf-8")

    found = find_latest_listings_log(tmp_path, "TEST")
    assert found == new
    found_other = find_latest_listings_log(tmp_path, "NOTEXIST")
    assert found_other is None


# ============================================================================
# 7e: listing_verifier
# ============================================================================
def test_listing_verifier_imports():
    """ebay_actions.listing_verifier が import 可能."""
    from ebay_actions import listing_verifier
    assert callable(listing_verifier.verify_listings)
    assert callable(listing_verifier.get_last_uploaded_item_ids)
    assert callable(listing_verifier._detect_qty_state)
    assert callable(listing_verifier.mark_verified)


def test_listing_verifier_detect_qty_state():
    """HTML パターン → qty 状態 判定."""
    from ebay_actions.listing_verifier import _detect_qty_state
    # ended
    state, hint = _detect_qty_state("foo This listing has ended bar")
    assert state == "ended"
    # qty zero (Out of stock)
    state, hint = _detect_qty_state("Out of stock!")
    assert state == "qty_zero"
    # 在庫切れ JP
    state, hint = _detect_qty_state("商品は在庫切れです")
    assert state == "qty_zero"
    # availability 数字 (qty 5)
    state, hint = _detect_qty_state("12 available; ship now")
    assert state == "qty_positive"
    assert "5" not in hint  # 12 だから
    # availability 数字 (qty 0)
    state, hint = _detect_qty_state("0 in stock")
    assert state == "qty_zero"
    # unknown
    state, hint = _detect_qty_state("random text")
    assert state == "unknown"


def test_listing_verifier_state_persistence(tmp_path, monkeypatch):
    """mark_verified → get_already_verified の roundtrip."""
    from ebay_actions import listing_verifier as lv
    fake_state = tmp_path / "verify_state.json"
    monkeypatch.setattr(lv, "VERIFY_STATE_FILE", fake_state)
    assert lv.get_already_verified() == set()
    lv.mark_verified(["A", "B"])
    assert lv.get_already_verified() == {"A", "B"}
    lv.mark_verified(["C"])
    assert lv.get_already_verified() == {"A", "B", "C"}


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
