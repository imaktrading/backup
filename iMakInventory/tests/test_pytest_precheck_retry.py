"""pytest precheck の retry / abort 判定 regression test.

★ 2026-08-13 制定。実害: 01:30 cycle の precheck が 120s timeout (status=error) で巡回 abort、
在庫監視が次 cycle (05:30) まで 4h 空白 = fail-OPEN 露出。検体テスト自体は数秒で通っており
(同日 00:00 cycle は 6.4s、21:30 cycle は 40.2s)、**検出ロジックは壊れていなかった**。
= 実行できなかっただけで巡回ごと落としていた。

仕様 (ここを壊したら 4h 空白が再発):
- status=error (timeout / 実行不能) は PYTEST_PRECHECK_ATTEMPTS 回まで retry する。
- status=failed (テストが実際に落ちた = DOM 仕様変更の疑い) は retry せず即 abort (fail-closed 維持)。
- passed になった時点で即 return (無駄な再実行をしない)。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _completed(rc: int, out: str = ""):
    m = MagicMock()
    m.returncode = rc
    m.stdout = out
    m.stderr = ""
    return m


@pytest.mark.offline
def test_timeout_is_retried_and_recovers():
    """timeout → retry で通れば passed (巡回は止めない)."""
    import run_cycle as rc
    calls = [subprocess.TimeoutExpired(cmd="pytest", timeout=300),
             _completed(0, "42 passed")]
    with patch.object(rc.subprocess, "run", side_effect=calls), \
         patch.object(rc.time, "sleep"):
        res = rc._phase_pytest_precheck(test_mode=True)
    assert res["status"] == "passed"
    assert res["attempts"] == 2


@pytest.mark.offline
def test_timeout_all_attempts_reports_error_with_attempt_count():
    """全 attempt timeout なら error。何回試したかを残す (silent にしない)."""
    import run_cycle as rc
    with patch.object(rc.subprocess, "run",
                      side_effect=subprocess.TimeoutExpired(cmd="pytest", timeout=300)), \
         patch.object(rc.time, "sleep"):
        res = rc._phase_pytest_precheck(test_mode=True)
    assert res["status"] == "error"
    assert res["attempts"] == rc.PYTEST_PRECHECK_ATTEMPTS
    assert "timeout" in res["error"]


@pytest.mark.offline
def test_test_failure_is_not_retried():
    """テストが落ちた場合は retry しない (検出ロジックの疑い → 即 fail-closed abort)."""
    import run_cycle as rc
    run_mock = MagicMock(return_value=_completed(1, "1 failed, 41 passed"))
    with patch.object(rc.subprocess, "run", run_mock), patch.object(rc.time, "sleep"):
        res = rc._phase_pytest_precheck(test_mode=True)
    assert res["status"] == "failed"
    assert res["attempts"] == 1
    assert run_mock.call_count == 1


@pytest.mark.offline
def test_pass_on_first_attempt_runs_once():
    import run_cycle as rc
    run_mock = MagicMock(return_value=_completed(0, "42 passed"))
    with patch.object(rc.subprocess, "run", run_mock):
        res = rc._phase_pytest_precheck(test_mode=True)
    assert res["status"] == "passed" and res["attempts"] == 1
    assert run_mock.call_count == 1


@pytest.mark.offline
def test_timeout_budget_covers_observed_worst_case():
    """実測の最悪値 (40s) に対して十分な timeout か = 負荷で即死しない余裕を持つ."""
    import run_cycle as rc
    assert rc.PYTEST_PRECHECK_TIMEOUT_SEC >= 240
    assert rc.PYTEST_PRECHECK_ATTEMPTS >= 2


@pytest.mark.offline
def test_abort_is_recorded_in_cycle_log():
    """precheck abort も cycle log に残す (停止した事実を履歴から消さない).

    ★ 2026-08-13: 01:30 の abort が decision_log に無く、後から稼働率を数えた時に
      「その時間の巡回は存在しない」ように見えた = 停止が履歴上 invisible だった。
    """
    import run_cycle as rc
    src = Path(rc.__file__).read_text(encoding="utf-8")
    abort_block = src.split('cycle_log["status"] = "aborted_pytest_precheck_failed"')[1]
    abort_block = abort_block.split("return cycle_log")[0]
    assert "_record_cycle_log(cycle_log)" in abort_block, "abort 経路で cycle log を記録していない"
