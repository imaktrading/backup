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


def test_sweeper_runs_off_the_ui_thread():
    """プロセス一覧の取得で画面を止めない (別スレッドで回す)。"""
    hq = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(hq, "control_panel.py"), encoding="utf-8").read()
    i = src.index("def _start_orphan_sweeper(")
    body = src[i:src.index(chr(10) + "def ", i + 10)]
    assert "threading.Thread(target=_sweep_orphan_drivers" in body
