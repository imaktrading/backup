"""Console の巡回の帯: 監視くんが LAPTOP に移った後は、スプシの最終チェック時刻を出す (残務 №373)。"""
import datetime
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "console"))
import watcher  # noqa: E402


def test_latest_check_parses_unpadded_dates():
    vals = ["2026/9/9 8:37:30", "2026/9/27 7:31:03", "", "壊れた値", "2026/6/2 10:44:39"]
    assert watcher.latest_check(vals) == datetime.datetime(2026, 9, 27, 7, 31, 3)


def test_remote_line():
    now = datetime.datetime(2026, 9, 27, 8, 0)
    assert "07:31" in watcher.remote_line(datetime.datetime(2026, 9, 27, 7, 31), now)
    assert "⚠️" in watcher.remote_line(datetime.datetime(2026, 9, 27, 4, 0), now)
    assert "読めません" in watcher.remote_line(None, now)


def test_server_uses_remote_line_when_nothing_local():
    src = open(os.path.join(os.path.dirname(__file__), "..", "console", "server.py"), encoding="utf-8").read()
    assert "if not running and not any(nexts.values()):" in src
    assert "watcher.remote_line(" in src
