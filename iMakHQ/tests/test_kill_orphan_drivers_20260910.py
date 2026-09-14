# -*- coding: utf-8 -*-
"""置き去りのブラウザだけを落とす (2026-09-10 ユーザー要望).

> 動きが遅くなるから、常に要らんものは落とす仕組みを入れて欲しい

落としてはいけないものが2つある。ここで固定する。
  1. ユーザーが自分で開いている Chrome (自動操作の目印が無いもの)
  2. **今 走っている仕事のブラウザ** — 2026-07-28 のユーザー判断
     (深夜の監視くん/リバイスくんの driver を巻き添えにしない)
実測 2026-09-10 06:58: 自動操作の chrome 19個は全部 走行中の run_cycle.py /
uniqlo scraper の持ち物で、落とすべき置き去りは0件だった。
"""
import os
import sys

TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
sys.path.insert(0, TOOLS)

import kill_orphan_drivers as K          # noqa: E402


def _p(pid, ppid, name, cmd="", created=100):
    return {"pid": pid, "ppid": ppid, "name": name, "cmd": cmd, "created": created}


def test_user_chrome_is_never_touched():
    """目印の無い Chrome は、持ち主が居なくても触らない。"""
    procs = [_p(10, 999, "chrome.exe", "chrome.exe --profile-directory=Default")]
    assert K.orphan_roots(procs) == []


def test_orphan_automation_chrome_is_killed():
    """持ち主 (python) が居ない自動操作 chrome は落とす。"""
    procs = [_p(10, 999, "chrome.exe", "chrome.exe --headless --remote-debugging-port=1")]
    assert K.orphan_roots(procs) == [10]


def test_running_job_keeps_its_browser():
    """走行中の仕事のブラウザは残す (監視くんを巻き添えにしない)。"""
    procs = [_p(5, 1, "pythonw3.11.exe", "run_cycle.py", created=50),
             _p(10, 5, "chrome.exe", "chrome.exe --headless", created=60)]
    assert K.orphan_roots(procs) == []


def test_only_the_root_is_listed():
    """ぶら下がりの chrome は個別に挙げない (親玉を木ごと止めれば消える)。"""
    procs = [_p(10, 999, "chrome.exe", "chrome.exe --headless", created=60),
             _p(11, 10, "chrome.exe", "chrome.exe --headless --type=renderer", created=61),
             _p(12, 10, "chrome.exe", "chrome.exe --headless --type=gpu", created=62)]
    assert K.orphan_roots(procs) == [10]


def test_recycled_pid_is_not_mistaken_for_the_owner():
    """親の番号が使い回されている (親の方が後に生まれている) なら持ち主なし。"""
    procs = [_p(5, 1, "pythonw3.11.exe", "別の仕事.py", created=900),
             _p(10, 5, "chrome.exe", "chrome.exe --headless", created=60)]
    assert K.orphan_roots(procs) == [10]


def test_chromedriver_is_always_automation():
    procs = [_p(10, 999, "chromedriver.exe", "")]
    assert K.orphan_roots(procs) == [10]


def test_unknown_creation_time_keeps_the_process():
    """起動時刻が判らない時は親子とみなす = 落とさない側に倒す。"""
    procs = [_p(5, 1, "pythonw3.11.exe", "run_cycle.py", created=None),
             _p(10, 5, "chrome.exe", "chrome.exe --headless", created=None)]
    assert K.orphan_roots(procs) == []


def test_panel_sweeps_at_startup_and_on_a_timer():
    """出品くんが起動時と定期の両方で掃除すること (入れ忘れ防止)。"""
    hq = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(hq, "control_panel.py"), encoding="utf-8").read()
    assert "_sweep_orphan_drivers(log=" in src, "起動時の掃除が無い"
    assert "_start_orphan_sweeper(root)" in src, "定期の掃除が無い"
    assert "SWEEP_EVERY_MS = 10 * 60 * 1000" in src


def test_root_search_is_killed_after_ten_minutes():
    """★2026-09-14: ディスク全体の検索は10分で落とす (持ち主が居ても)。"""
    procs = [_p(1, 0, "claude.exe", created=0),
             _p(20, 1, "find.exe", '"C:\\Program Files\\Git\\usr\\bin\\find.exe" / -iname *x*', created=100)]
    assert K.orphan_roots(procs, now=100 + 9 * 60) == []
    assert K.orphan_roots(procs, now=100 + 10 * 60) == [20]


def test_normal_find_is_never_touched():
    """フォルダを指定した検索は長くても触らない。"""
    procs = [_p(20, 999, "find.exe", "find.exe /c/dev/iMak -name *.py", created=0)]
    assert K.orphan_roots(procs, now=10 ** 6) == []


def test_orphan_test_run_is_killed():
    """★2026-09-14: セッションが消えた後に残ったテスト (claude → bash → bash → python) は落とす。"""
    procs = [_p(30, 777, "bash.exe", created=100),
             _p(31, 30, "bash.exe", created=101),
             _p(32, 31, "python3.11.exe", "python.exe -m pytest -q", created=102)]
    assert K.orphan_roots(procs, now=102 + 3 * 60) == [32]


def test_precommit_test_run_is_kept():
    """git が生きている pre-commit のテストは残す。"""
    procs = [_p(1, 0, "git.exe", created=90),
             _p(30, 1, "bash.exe", created=100),
             _p(32, 30, "python3.11.exe", "python -m pytest tests/ --tb=short -q", created=102)]
    assert K.orphan_roots(procs, now=102 + 3600) == []


def test_just_orphaned_test_is_given_time():
    """終わった直後 (2分未満) は片付け中かもしれないので触らない。"""
    procs = [_p(32, 777, "python3.11.exe", "python -m pytest -q", created=100)]
    assert K.orphan_roots(procs, now=100 + 60) == []


def test_without_clock_search_and_tests_are_kept():
    """現在時刻が無い時は、時間で判定するものは落とさない側。"""
    procs = [_p(20, 999, "find.exe", "find / -iname x", created=0),
             _p(32, 777, "python3.11.exe", "python -m pytest -q", created=0)]
    assert K.orphan_roots(procs) == []


def test_japanese_command_line_does_not_break_the_list():
    """★2026-09-14: cp932 の日本語 (2バイト目が 0x5C) を含む一覧が読めること。

    従来は utf-8 の replace で読んで JSON が壊れ、掃除が毎回「何もしない」で終わっていた。
    """
    import json
    raw = json.dumps([{"pid": 1, "name": "x.exe", "cmd": "表示 ソース"}],
                     ensure_ascii=False).encode("cp932")
    assert json.loads(K.decode_ps_output(raw))[0]["cmd"] == "表示 ソース"
    assert json.loads(K.decode_ps_output(raw.decode("cp932").encode("utf-8")))[0]["pid"] == 1


def test_sweeper_runs_off_the_ui_thread():
    """プロセス一覧の取得で画面を止めない (別スレッドで回す)。"""
    hq = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(hq, "control_panel.py"), encoding="utf-8").read()
    i = src.index("def _start_orphan_sweeper(")
    body = src[i:src.index(chr(10) + "def ", i + 10)]
    assert "threading.Thread(target=_sweep_orphan_drivers" in body
