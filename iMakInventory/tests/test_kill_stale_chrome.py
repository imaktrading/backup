"""orphan chrome 一掃ヘルパー (_kill_stale_scraper_chrome) の offline テスト.

2026-06-12: mercari driver 再起動失敗で headless chrome が orphan 累積 →
「chrome not reachable」で driver 完全不動の事故。 旧 kill は process 名/フィルタの
二重バグで一つも kill できていなかった。 本ヘルパーで cycle 開始時に一掃する。

2026-07-28: その旧実装は「--headless chrome 全部 + undetected_chromedriver 全部」を
マシン全体で kill していたため、**他プロジェクト (公式監視くん check_ebay_login /
Catalog / Harvest 等) の headless chrome を巻き込む越境事故**になり得た。
自分の profile 配下 + 真の orphan driver だけを対象にする限定 kill に変更。
"""
import subprocess

import pytest

import monitor_listings as ml

pytestmark = pytest.mark.offline

MINE_MERCARI = r"C:\Users\imax2\local_data\iMakMercari\chrome_profile"
MINE_AMAZON = r"C:\Users\imax2\local_data\iMakInventory\chrome_profile_amazon"
PROFILES = (MINE_MERCARI.lower(), MINE_AMAZON.lower())


def _p(pid, name, cmd="", ppid=1):
    return {"ProcessId": pid, "ParentProcessId": ppid, "Name": name, "CommandLine": cmd}


# ------------------------------------------------------------------ 選定ロジック
def test_kills_own_headless_chrome():
    procs = [_p(10, "chrome.exe", f'chrome.exe --headless --user-data-dir="{MINE_MERCARI}"'),
             _p(11, "chrome.exe", f'chrome.exe --headless --user-data-dir={MINE_AMAZON}')]
    assert sorted(ml._select_stale_scraper_pids(procs, PROFILES)) == [10, 11]


def test_keeps_other_projects_headless_chrome():
    """★越境防止: 他プロジェクトの headless chrome は profile 不一致なので残す"""
    procs = [_p(20, "chrome.exe",
                r'chrome.exe --headless --user-data-dir="C:\Users\imax2\local_data\iMakCatalog\prof"'),
             _p(21, "chrome.exe", "chrome.exe --headless")]           # profile 指定なし = 誰のか不明
    assert ml._select_stale_scraper_pids(procs, PROFILES) == []


def test_keeps_user_normal_browser():
    procs = [_p(30, "chrome.exe", f'chrome.exe --user-data-dir="{MINE_MERCARI}"')]   # headless でない
    assert ml._select_stale_scraper_pids(procs, PROFILES) == []


def test_kills_only_orphan_driver():
    """親が死んでいる driver だけ kill。稼働中 (親 python 生存) の driver は他所のものでも残す"""
    procs = [_p(1000, "python.exe"),                                   # 生存中の親
             _p(40, "undetected_chromedriver.exe", "uc", ppid=1000),   # 稼働中 → 残す
             _p(41, "undetected_chromedriver.exe", "uc", ppid=9999)]   # 親不在 = orphan → kill
    assert ml._select_stale_scraper_pids(procs, PROFILES) == [41]


def test_unknown_commandline_is_not_killed():
    """CommandLine が取れない (権限等) なら触らない = fail-safe"""
    procs = [_p(50, "chrome.exe", None), _p(51, "chrome.exe", "")]
    assert ml._select_stale_scraper_pids(procs, PROFILES) == []


def test_self_pid_never_killed():
    procs = [_p(60, "chrome.exe", f'--headless --user-data-dir={MINE_AMAZON}')]
    assert ml._select_stale_scraper_pids(procs, PROFILES, self_pid=60) == []


def test_no_profile_dirs_kills_no_chrome():
    """profile が特定できない環境では chrome を1つも kill しない (安全側)"""
    procs = [_p(70, "chrome.exe", f'--headless --user-data-dir={MINE_MERCARI}')]
    assert ml._select_stale_scraper_pids(procs, ()) == []


def test_own_profile_dirs_resolves_real_paths():
    dirs = ml._own_profile_dirs()
    assert len(dirs) == 2 and all(d == d.lower() for d in dirs)
    assert any("mercari" in d for d in dirs) and any("amazon" in d for d in dirs)


# ------------------------------------------------------------------ 実行部
def test_noop_on_non_windows(monkeypatch):
    monkeypatch.setattr(ml.sys, "platform", "linux")
    called = {"n": 0}
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: called.__setitem__("n", called["n"] + 1))
    ml._kill_stale_scraper_chrome(log=lambda *a: None)
    assert called["n"] == 0          # 非 win32 では subprocess を呼ばない


def test_win32_enumerates_then_kills_selected(monkeypatch):
    monkeypatch.setattr(ml.sys, "platform", "win32")
    calls = []

    class R:
        def __init__(self, out):
            self.stdout = out

    def fake_run(cmd, **kw):
        calls.append(cmd)
        if "ConvertTo-Json" in " ".join(cmd):
            import json as _json
            return R(_json.dumps([
                {"ProcessId": 10, "ParentProcessId": 1, "Name": "chrome.exe",
                 "CommandLine": f"chrome --headless --user-data-dir={MINE_AMAZON}"},
                {"ProcessId": 20, "ParentProcessId": 1, "Name": "chrome.exe",
                 "CommandLine": r"chrome --headless --user-data-dir=C:\other\prof"},
            ]))
        return R("")

    monkeypatch.setattr(subprocess, "run", fake_run)
    ml._kill_stale_scraper_chrome(log=lambda *a: None)
    kill_cmd = " ".join(calls[-1])
    assert "Stop-Process -Id 10" in kill_cmd      # 自分の profile のみ
    assert "20" not in kill_cmd                   # 他プロジェクトは kill しない


def test_win32_no_target_skips_kill(monkeypatch):
    monkeypatch.setattr(ml.sys, "platform", "win32")
    calls = []

    class R:
        stdout = "[]"

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return R()

    monkeypatch.setattr(subprocess, "run", fake_run)
    ml._kill_stale_scraper_chrome(log=lambda *a: None)
    assert len(calls) == 1                        # 列挙のみ、kill は呼ばない


def test_exception_is_swallowed(monkeypatch):
    """kill 失敗しても cycle を止めない (fail-safe)."""
    monkeypatch.setattr(ml.sys, "platform", "win32")

    def boom(*a, **k):
        raise RuntimeError("powershell not found")

    monkeypatch.setattr(subprocess, "run", boom)
    ml._kill_stale_scraper_chrome(log=lambda *a: None)
