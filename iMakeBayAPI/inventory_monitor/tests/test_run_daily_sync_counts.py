"""run_daily の件名・冒頭が ebay_supplier_sync の実行件数を数えること (2026-10-02 「処理 0 件」誤表示)."""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import run_daily as R  # noqa: E402


def _rec(kind, action, ack="Warning"):
    return {"iid": "1", "kind": kind, "action": action, "ack": ack}


def _report(res):
    zero, restore = R._sync_counts(res)
    t = datetime(2026, 10, 2, 19, 0)
    monitor = {"listings": 95, "updates": 794, "needs_action": 23, "prev_needs_action": 113,
               "errors": 0}
    steps = [("monitor", True), ("zero", True), ("audit_buyable", True)]
    return R._format_report(t, t, monitor, zero, restore, steps)


def test_three_zeros_are_counted():
    res = {"done": {"zero": [_rec(3, "zero"), _rec(2, "zero"), _rec(1, "zero")],
                    "restore": [], "failed": []}}
    zero, restore = R._sync_counts(res)
    assert (zero["variation_executed"], zero["single_executed"]) == (2, 1)
    assert zero["variation_success"] is True and zero["single_success"] is True
    assert restore["variation_executed"] == 0 and restore["single_executed"] == 0
    subject, body = _report(res)
    assert "処理 3 件" in subject and "正常 (qty 変更実施)" in subject
    assert "対象なし" not in body


def test_failed_restore_is_ng():
    res = {"done": {"zero": [], "restore": [_rec(2, "restore", "Success")],
                    "failed": [_rec(3, "restore", "Failure")]}}
    zero, restore = R._sync_counts(res)
    assert restore["variation_executed"] == 2 and restore["ng"] == 1
    assert restore["variation_success"] is False
    assert "要対応" in _report(res)[0]


def test_no_result_file_is_zero():
    zero, restore = R._sync_counts({})
    assert zero["variation_executed"] == zero["single_executed"] == 0
    assert "処理 0 件" in _report({})[0]


def test_zero_step_failure_is_reported():
    zero, restore = R._sync_counts({})
    t = datetime(2026, 10, 2, 19, 0)
    monitor = {"listings": 1, "updates": 0, "needs_action": 0, "prev_needs_action": 0, "errors": 0}
    subject, _ = R._format_report(t, t, monitor, zero, restore, [("monitor", True), ("zero", False)])
    assert "異常" in subject
