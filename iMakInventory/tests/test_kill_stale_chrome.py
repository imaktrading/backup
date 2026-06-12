"""orphan chrome 一掃ヘルパー (_kill_stale_scraper_chrome) の offline テスト.

2026-06-12: mercari driver 再起動失敗で headless chrome が orphan 累積 →
「chrome not reachable」で driver 完全不動の事故。 旧 kill は process 名/フィルタの
二重バグで一つも kill できていなかった。 本ヘルパーで cycle 開始時に一掃する。
"""
import subprocess

import pytest

import monitor_listings as ml

pytestmark = pytest.mark.offline


def test_noop_on_non_windows(monkeypatch):
    monkeypatch.setattr(ml.sys, "platform", "linux")
    called = {"n": 0}
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: called.__setitem__("n", called["n"] + 1))
    ml._kill_stale_scraper_chrome(log=lambda *a: None)
    assert called["n"] == 0          # 非 win32 では subprocess を呼ばない


def test_win32_invokes_powershell_with_headless_filter(monkeypatch):
    monkeypatch.setattr(ml.sys, "platform", "win32")
    captured = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        captured["kw"] = kw
        return None

    monkeypatch.setattr(subprocess, "run", fake_run)
    ml._kill_stale_scraper_chrome(log=lambda *a: None)
    cmd = captured["cmd"]
    assert cmd[0] == "powershell"
    joined = " ".join(cmd)
    assert "undetected_chromedriver" in joined      # driver も kill
    assert "--headless" in joined                   # ユーザーブラウザ温存 (headless のみ)
    assert "chrome.exe" in joined


def test_exception_is_swallowed(monkeypatch):
    """kill 失敗しても cycle を止めない (fail-safe)."""
    monkeypatch.setattr(ml.sys, "platform", "win32")

    def boom(*a, **k):
        raise RuntimeError("powershell not found")

    monkeypatch.setattr(subprocess, "run", boom)
    # 例外を投げずに返ること
    ml._kill_stale_scraper_chrome(log=lambda *a: None)
