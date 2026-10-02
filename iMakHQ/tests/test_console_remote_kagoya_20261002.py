"""神風のボタンを KAGOYA で動かす (2026-10-02 段階B)。remote_buttons に無いボタンは今までどおり。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "console"))
import server  # noqa: E402

CFG = {"host": "h", "user": "u", "key": "k", "remote_buttons": ["補URL"]}


def test_local_button_is_unchanged():
    assert server.remote_command({"label": "PSA自動", "cwd": "C:/x"}, ["python", "a.py"], CFG) is None
    assert server.remote_command({"label": "補URL", "cwd": "C:/x"}, ["python", "a.py"], {}) is None


def test_remote_button_builds_ssh_with_tunnel():
    cmd = server.remote_command({"label": "補URL", "cwd": "C:/dev/iMak/iMakHQ/tools", "env": {"A": "1"}},
                                ["python", "psa_hoju_fill.py", "confirm", "--limit=15"], CFG)
    assert cmd[0] == "ssh" and "u@h" in cmd
    assert "%d:127.0.0.1:%d" % (server.REVIEW_PORT, server.REVIEW_PORT) in cmd
    remote = cmd[-1]
    assert "Set-Location 'C:\\dev\\iMak\\iMakHQ\\tools'" in remote
    assert "'psa_hoju_fill.py' 'confirm' '--limit=15'" in remote
    assert "$env:IMAK_NO_BROWSER='1'" in remote and "$env:A='1'" in remote
    assert "OutputEncoding" in remote


def test_review_line_regex():
    m = server._REVIEW_RE.search("  ブラウザで確認してください → http://127.0.0.1:18765/")
    assert m and m.group(1) == "http://127.0.0.1:18765/"
