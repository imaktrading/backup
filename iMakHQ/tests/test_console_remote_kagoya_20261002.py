"""神風のボタンを KAGOYA で動かす (2026-10-02 段階B)。remote_buttons に無いボタンは今までどおり。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "console"))
import server  # noqa: E402

CFG = {"host": "h", "user": "u", "key": "k", "remote_buttons": ["補URL"]}


def test_local_button_is_unchanged():
    assert server.remote_command({"label": "PSA自動", "cwd": "C:/x"}, ["python", "a.py"], CFG) is None
    assert server.remote_command({"label": "補URL", "cwd": "C:/x"}, ["python", "a.py"], {}) is None


def test_remote_button_goes_through_kagoya_button():
    """送る → KAGOYA で動かす → 取り込む は kagoya_button.py が受け持つ (2026-10-02)。"""
    cmd = server.remote_command({"label": "補URL", "cwd": "C:/dev/iMak/iMakHQ/tools", "env": {"A": "1"}},
                                ["python", "psa_hoju_fill.py", "confirm", "--limit=15"], CFG)
    assert cmd[0] == sys.executable and cmd[4].endswith("kagoya_button.py")
    assert cmd[cmd.index("--cwd") + 1] == "C:/dev/iMak/iMakHQ/tools"
    assert cmd[cmd.index("--env") + 1] == "A=1"
    assert cmd[cmd.index("--") + 1:] == ["psa_hoju_fill.py", "confirm", "--limit=15"]


def test_review_line_regex():
    m = server._REVIEW_RE.search("  ブラウザで確認してください → http://127.0.0.1:18765/")
    assert m and m.group(1) == "http://127.0.0.1:18765/"
