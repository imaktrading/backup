"""再起動前の lock は pid が使い回されていても死んでいる扱い (2026-09-24).

実測: CAND の lock (pid=16060, 05:00) が 07:10 の再起動後 svchost.exe の pid と重なり、
tasklist では「生存」→ 次の巡回が 45分待って飛ぶところだった。
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import socket  # noqa: E402

import run_cycle as rc  # noqa: E402


def _content(pid, ago_min):
    ts = (datetime.now() - timedelta(minutes=ago_min)).isoformat()
    return f"pid={pid} host={socket.gethostname()} ts={ts}"


def test_lock_before_boot_is_dead(monkeypatch):
    monkeypatch.setattr(rc, "_last_boot_time", lambda: datetime.now() - timedelta(minutes=60))
    import os
    assert rc._lock_pid_alive(_content(os.getpid(), 120)) is False   # pid は生きていても


def test_lock_after_boot_uses_pid(monkeypatch):
    monkeypatch.setattr(rc, "_last_boot_time", lambda: datetime.now() - timedelta(minutes=60))
    import os
    assert rc._lock_pid_alive(_content(os.getpid(), 10)) is True


def test_unknown_boot_time_falls_back_to_pid(monkeypatch):
    monkeypatch.setattr(rc, "_last_boot_time", lambda: None)
    import os
    assert rc._lock_pid_alive(_content(os.getpid(), 120)) is True
