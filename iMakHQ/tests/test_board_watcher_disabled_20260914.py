"""見張り役 (dispatch watcher) を止めてある間は「止まっている」警告を出さない (2026-09-14).

ユーザー判断「廃止して / 必要な時に再開するから」。警告を出し続けると誰かが再起動してしまう。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import worktree_board as wb  # noqa: E402


def test_disabled_shows_no_alarm():
    line = wb.watcher_status_line(None, True)
    assert "停止中" in line and "⚠️" not in line and "/run" not in line


def test_enabled_but_dead_still_alarms():
    assert "⚠️" in wb.watcher_status_line(None, False)
    assert "⚠️" in wb.watcher_status_line(900, False)


def test_enabled_and_alive():
    assert "稼働中" in wb.watcher_status_line(10, False)
