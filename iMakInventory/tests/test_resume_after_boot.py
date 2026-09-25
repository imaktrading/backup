"""起動後の再開チェック (tools/resume_after_boot.py) の「止まった巡回か」判定 (2026-09-24)."""
from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import resume_after_boot as R  # noqa: E402


def _env(tmp_path, monkeypatch, alive=()):
    monkeypatch.setattr(R, "DECISION_LOG_DIR", tmp_path)
    monkeypatch.setattr(R, "pid_alive", lambda pid: pid in alive)


def _lock(tmp_path, name, pid, ago_min):
    ts = (datetime.now() - timedelta(minutes=ago_min)).isoformat()
    (tmp_path / name).write_text(f"pid={pid} host=iMak ts={ts}\n", encoding="utf-8")


def test_nothing_to_do(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    assert R.interrupted("SHEET", ".cycle.lock") is None


def test_checkpoint_means_interrupted(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    (tmp_path / "checkpoint_SHEET.jsonl").write_text("{}\n", encoding="utf-8")
    assert R.interrupted("SHEET", ".cycle.lock")


def test_running_cycle_is_left_alone(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch, alive={123})
    (tmp_path / "checkpoint_SHEET.jsonl").write_text("{}\n", encoding="utf-8")
    _lock(tmp_path, ".cycle.lock", 123, 10)
    assert R.interrupted("SHEET", ".cycle.lock") is None


def test_dead_lock_without_finish_record(tmp_path, monkeypatch):
    """1行目より前 (起動直後の点検中) に落ちた = 途中経過なしでも止まった扱い."""
    _env(tmp_path, monkeypatch)
    _lock(tmp_path, ".cycle_LOW.lock", 999, 30)
    assert R.interrupted("LOW", ".cycle_LOW.lock")


def test_dead_lock_but_cycle_finished(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    _lock(tmp_path, ".cycle_LOW.lock", 999, 90)
    (tmp_path / f"cycle_{datetime.now():%Y%m%d_%H%M%S}.jsonl").write_text(
        '{"sheet": "low", "sheet_label": "SHEET"}', encoding="utf-8")
    assert R.interrupted("LOW", ".cycle_LOW.lock") is None


def test_other_cycles_finish_does_not_count(tmp_path, monkeypatch):
    """HIGH が終わっても、止まった CAND は止まったまま."""
    _env(tmp_path, monkeypatch)
    _lock(tmp_path, ".cycle_CAND.lock", 999, 90)
    (tmp_path / f"cycle_{datetime.now():%Y%m%d_%H%M%S}.jsonl").write_text(
        '{"sheet": null, "sheet_label": "SHEET"}', encoding="utf-8")
    assert R.interrupted("CAND", ".cycle_CAND.lock")


def test_old_dead_lock_ignored(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    _lock(tmp_path, ".cycle.lock", 999, 60 * 10)
    assert R.interrupted("SHEET", ".cycle.lock") is None


def test_old_checkpoint_ignored(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    p = tmp_path / "checkpoint_CAND.jsonl"
    p.write_text("{}\n", encoding="utf-8")
    old = time.time() - 9 * 3600
    os.utime(p, (old, old))
    assert R.interrupted("CAND", ".cycle_CAND.lock") is None


def test_unreadable_lock_reruns(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    (tmp_path / ".cycle.lock").write_text("???", encoding="utf-8")
    assert R.interrupted("SHEET", ".cycle.lock")


def test_order_high_first_and_drain_first(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    for lab in ("CAND", "SHEET", "LOW"):
        (tmp_path / f"checkpoint_{lab}.jsonl").write_text("{}\n", encoding="utf-8")
    ran = []
    monkeypatch.setattr(R, "run_task", lambda name: ran.append(name) or True)
    monkeypatch.setattr(R, "wait_cycle", lambda *a, **k: None)
    monkeypatch.setattr(R, "wait_others_idle", lambda: None)
    monkeypatch.setattr(R, "LOG_FILE", tmp_path / "resume.log")
    R.main()
    assert ran == ["iMakInventory_DrainTakedowns_Hourly", "iMakInventory_Cycle",
                   "iMakInventory_Cycle_LOW", "iMakInventory_Cycle_CAND"]


def test_lock_from_before_reboot_is_dead_even_if_pid_reused(tmp_path, monkeypatch):
    """再起動後に同じ pid を別プロセス (svchost 等) が使っていても、再起動前の lock は死んでいる."""
    _env(tmp_path, monkeypatch, alive={16060})
    _lock(tmp_path, ".cycle_CAND.lock", 16060, 120)
    monkeypatch.setattr(R, "last_boot_time", lambda: datetime.now() - timedelta(minutes=60))
    assert R.interrupted("CAND", ".cycle_CAND.lock")


def test_waits_while_another_cycle_runs(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch, alive={77})
    monkeypatch.setattr(R, "POLL_SEC", 0)
    _lock(tmp_path, ".cycle.lock", 77, 5)                      # HIGH 走行中
    calls = {"n": 0}

    def _alive(pid, ts):
        calls["n"] += 1
        if calls["n"] >= 3:                                       # 3回目の確認で HIGH が終わる
            (tmp_path / ".cycle.lock").unlink(missing_ok=True)
        return pid == 77 and (tmp_path / ".cycle.lock").exists()

    monkeypatch.setattr(R, "lock_owner_alive", _alive)
    monkeypatch.setattr(R, "LOG_FILE", tmp_path / "resume.log")
    R.wait_others_idle()
    assert not (tmp_path / ".cycle.lock").exists()


def _periodic_env(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    ran = []
    monkeypatch.setattr(R, "run_task", lambda name: ran.append(name) or True)
    monkeypatch.setattr(R, "wait_cycle", lambda *a, **k: None)
    monkeypatch.setattr(R, "wait_others_idle", lambda: None)
    monkeypatch.setattr(R, "LOG_FILE", tmp_path / "resume.log")
    monkeypatch.setattr(R, "RETRY_STATE", tmp_path / "retry.json")
    alerts = []
    monkeypatch.setattr(R, "_alert_gave_up", lambda *a: alerts.append(a))
    return ran, alerts


def test_periodic_silent_when_nothing_to_do(tmp_path, monkeypatch):
    ran, _ = _periodic_env(tmp_path, monkeypatch)
    assert R.main(periodic=True) == 0
    assert ran == [] and not (tmp_path / "resume.log").exists()   # 何も起動せず、ログも残さない


def test_periodic_relaunches_crashed_cycle_then_gives_up_after_3(tmp_path, monkeypatch):
    ran, alerts = _periodic_env(tmp_path, monkeypatch)
    (tmp_path / "checkpoint_SHEET.jsonl").write_text('{"_checkpoint": 1, "started": "2026-09-25T13:31:31"}\n', encoding="utf-8")
    for _ in range(3):
        R.main(periodic=True)
    assert ran.count("iMakInventory_Cycle") == 3
    R.main(periodic=True)                                              # 4回目: 走らせない + 告知1回
    R.main(periodic=True)
    assert ran.count("iMakInventory_Cycle") == 3 and len(alerts) == 1


def test_periodic_counts_per_interruption(tmp_path, monkeypatch):
    """別の回の途中経過になったら数え直す."""
    ran, _ = _periodic_env(tmp_path, monkeypatch)
    ck = tmp_path / "checkpoint_SHEET.jsonl"
    ck.write_text('{"_checkpoint": 1, "started": "2026-09-25T13:31:31"}\n', encoding="utf-8")
    for _ in range(3):
        R.main(periodic=True)
    ck.write_text('{"_checkpoint": 1, "started": "2026-09-25T19:30:00"}\n', encoding="utf-8")
    R.main(periodic=True)
    assert ran.count("iMakInventory_Cycle") == 4
