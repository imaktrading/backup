# -*- coding: utf-8 -*-
"""補URL夜間検索のボタン表示 (2026-08-21 ユーザー指摘).

> 「検索できる47件ってなっているから、押さないといけないのかなと思ってしまう」

slice2 は **毎晩23:30 の定期タスクで自動で走る**。押す必要は無い。
件数だけ出すと「やり残し」に見えるので、自動で走ることを先に書く。

ただし **自動が止まっている時に「自動で走ります」と出してはいけない**。
誰も押さないまま止まり続ける (ラベルに嘘を書かない)。
"""
from __future__ import annotations

import os
import subprocess
import sys

HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HQ)

import control_panel as C                                       # noqa: E402


def _fake(returncode, out):
    class R:
        pass
    r = R()
    r.returncode = returncode
    r.stdout = out.encode("cp932")
    return r


def _run(monkeypatch, returncode, out):
    C._NIGHTLY_CACHE.clear()
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _fake(returncode, out))
    got = C.nightly_search_state()
    C._NIGHTLY_CACHE.clear()
    return got


NL = chr(10)
BS = chr(92)          # タスク名の先頭の \ (エスケープ警告を出さないため)

OK_CSV = ('"タスク名","次回の実行時刻","状態"' + NL
          + '"' + BS + 'iMakHQ_HojuSearch_2330","2026/08/21 23:30:00","準備完了"' + NL)


def test_動いていれば時刻を返す(monkeypatch):
    got = _run(monkeypatch, 0, OK_CSV)
    assert got["ok"] is True and got["at"] == "23:30"


def test_無効なら止まっていると返す(monkeypatch):
    ng = OK_CSV.replace("準備完了", "無効")
    got = _run(monkeypatch, 0, ng)
    assert got["ok"] is False and "無効" in got["why"]


def test_タスクが無ければ止まっていると返す(monkeypatch):
    got = _run(monkeypatch, 1, "")
    assert got["ok"] is False and "ありません" in got["why"]


def test_確認できなくても自動と言い切らない(monkeypatch):
    """schtasks が落ちた時に「自動で走ります」と出すと嘘になる."""
    def boom(*a, **k):
        raise OSError("x")
    C._NIGHTLY_CACHE.clear()
    monkeypatch.setattr(subprocess, "run", boom)
    got = C.nightly_search_state()
    C._NIGHTLY_CACHE.clear()
    assert got["ok"] is False
