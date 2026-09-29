# -*- coding: utf-8 -*-
"""神風が夜間バッチの処理を「前のサーバの走行」と見間違えない / 終わったら実行中を外す (2026-09-29)。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "console"))

import server as S  # noqa: E402


def test_batch_parents_are_not_console_runs():
    assert S.is_batch_parent(r'C:\Windows\system32\cmd.exe /c ""C:\dev\iMak\iMakHQ\tools\run_hoju_search.bat" "')
    assert S.is_batch_parent("wscript.exe //nologo C:\\dev\\iMak_data\\tools\\run_min.vbs x.bat")
    assert not S.is_batch_parent(None)                       # 親が居ない (前のサーバが消えた) = 拾う対象
    assert not S.is_batch_parent("python server.py")


def test_finished_orphan_is_released(monkeypatch):
    monkeypatch.setattr(S, "pid_alive", lambda pid: False)
    S._ORPHAN_SEEN["at"] = 0
    S.STATE["job"] = {"label": "x (前のサーバの走行)", "running": True, "orphan_pid": 99999}
    S.settle_orphan()
    assert S.STATE["job"]["running"] is False
