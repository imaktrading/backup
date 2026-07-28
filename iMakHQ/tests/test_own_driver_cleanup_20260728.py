"""driver 後片付けを「自分が起こした分だけ」に限定した回帰テスト (2026-07-28).

旧実装は run 開始時に undetected_chromedriver を **全部** kill していた。
深夜は 01:30 監視くん Cycle / 04:00 Backup / 04:30 リバイスくん が動いており、
01:30 の cycle が長引いたまま 03:00 の本 run が始まると **監視くんの driver を殺す**
= 取下げ処理の途中で driver が消える危険側の失敗。

ユーザー判断(2026-07-28): 他プロセスには触らず、自分の子プロセスだけ後片付けする。
"""
import inspect
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import psa_hoju_fill as P  # noqa: E402


def test_global_kill_is_disabled():
    """互換のため関数は残すが、他プロセスを kill してはいけない。"""
    src = inspect.getsource(P._clean_orphan_chrome)
    assert "Stop-Process" not in src
    assert P._clean_orphan_chrome() is None


def test_ownership_is_parent_based():
    """所有権は親プロセスID で判定する (同時刻に別ジョブが driver を起こしても取り違えない)。"""
    src = inspect.getsource(P._own_driver_pids)
    assert "ParentProcessId" in src
    assert "os.getpid()" in src


def test_cleanup_kills_only_listed_pids(monkeypatch):
    calls = {}

    class _R:
        stdout = ""

    def _fake_run(argv, **kw):
        calls["cmd"] = argv[-1]
        return _R()

    monkeypatch.setattr(P, "_own_driver_pids", lambda: [111, 222])
    import subprocess
    monkeypatch.setattr(subprocess, "run", _fake_run)
    assert P._cleanup_own_drivers() == 2
    assert "Stop-Process -Id 111,222" in calls["cmd"]


def test_cleanup_is_noop_without_own_pids(monkeypatch):
    monkeypatch.setattr(P, "_own_driver_pids", lambda: [])
    assert P._cleanup_own_drivers() == 0


def test_run_does_not_kill_at_start():
    """run 開始時に一括 kill を呼ばないこと(呼ぶと他ジョブを巻き込む)。"""
    src = inspect.getsource(P.run_night_search)
    assert "_clean_orphan_chrome()" not in src
    assert "_cleanup_own_drivers()" in src
