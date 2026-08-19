"""lock 解放待ち上限を label ごとに変えられること (2026-08-19).

事故: SHEET 巡回の所要が 85分 → 167分 に伸び、その 75 分後に始まる LOW 巡回が
45 分待っても lock を取れず 2 回連続 skip。LOW シート 512 行が 19.5h 監視されず、
売切を検知できない = 取下げ漏れの窓が開いた (08-18 22:45 / 08-19 06:45)。

LOW は「待てば走れる」だけなので、待ち上限を Task Scheduler 側から伸ばせるようにする。
ここで固定するのは以下:
  - --lock-wait-minutes を渡すと、その値で lock 解放を待つ
  - 渡さなければ従来どおり LOCK_WAIT_MINUTES (45 分)
  - skip した時の waited_minutes に実際の待ち上限が残る (後から検証できる)
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import run_cycle  # noqa: E402


def _run_skipped(**kwargs):
    """lock が取れない状況を作って run_cycle を skip 経路に流し、(呼出引数, cycle_log) を返す."""
    with patch.object(run_cycle, "_acquire_lock", return_value=False) as acq, \
         patch.object(run_cycle, "_record_cycle_log", return_value=Path("dummy.jsonl")), \
         patch.object(run_cycle, "_notify_toast"), \
         patch.object(run_cycle, "_check_cycle_staleness", return_value=[]):
        log = run_cycle.run_cycle(sheet="low", **kwargs)
    return acq.call_args, log


def test_default_wait_is_unchanged():
    """指定しなければ従来の 45 分 (既存 SHEET 巡回の挙動を変えない)."""
    call, log = _run_skipped()

    assert call.kwargs["wait_minutes"] == run_cycle.LOCK_WAIT_MINUTES
    assert log["waited_minutes"] == run_cycle.LOCK_WAIT_MINUTES


def test_explicit_wait_is_used():
    """LOW 枠は長く待てる (SHEET 巡回 167 分 + LOW 開始差 75 分 を吸収する)."""
    call, log = _run_skipped(lock_wait_minutes=150)

    assert call.kwargs["wait_minutes"] == 150
    assert log["waited_minutes"] == 150
    assert log["status"] == "skipped_lock_held"


def test_negative_wait_is_clamped_to_zero():
    """負値で待ち時間計算が壊れない (即諦める = 従来の 0 相当)."""
    call, _ = _run_skipped(lock_wait_minutes=-10)

    assert call.kwargs["wait_minutes"] == 0


def test_test_mode_never_waits():
    """test 実行が本番 cycle の裏で最大 150 分ぶら下がらないこと."""
    call, _ = _run_skipped(lock_wait_minutes=150, test_mode=True)

    assert call.kwargs["wait_minutes"] == 0
