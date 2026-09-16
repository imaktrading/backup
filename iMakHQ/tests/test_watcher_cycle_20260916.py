# -*- coding: utf-8 -*-
"""監視くんの巡回を Console に出す (2026-09-16)。

ユーザー「その時間帯は意識するようにできるから。次回開始時間と終了予定時間がわかれば、
その時間帯は軽め作業にする」。

実測の裏付け: 2026-09-16 15:02 にメモリの空きが 2% まで落ちた。主因は VS Code ではなく
**巡回が2本重なって Chrome が42プロセス 5.5GB** 使っていたこと。17:12 には巡回が終わり
空き47%に戻った。つまり「重い時間帯」は巡回の時間帯とほぼ同じ。

Windows のタスク履歴ログは無効で所要時間が取れないため、Console が自分で記録する。
"""
import datetime
import os
import sys

HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HQ, "console"))

import watcher as W  # noqa: E402

NOW = datetime.datetime(2026, 9, 16, 15, 0, 0)


def test_tells_which_cycle_from_the_command_line():
    assert W.task_of_cmdline("pythonw.exe -u run_cycle.py --sheet low") == "iMakInventory_Cycle_LOW"
    assert W.task_of_cmdline("pythonw.exe -u run_cycle.py --sheet-id 19kj") == "iMakInventory_Cycle"
    assert W.task_of_cmdline("pythonw.exe server.py") is None


def test_records_a_run_when_it_finishes():
    """走っている間は open、消えたら done に1本 足す。"""
    start = datetime.datetime(2026, 9, 16, 13, 30, 0)
    runs = W.update_runs({}, {"iMakInventory_Cycle": start}, start)
    assert runs["iMakInventory_Cycle"]["open"].startswith("2026-09-16T13:30")
    runs = W.update_runs(runs, {}, start + datetime.timedelta(minutes=95))
    rec = runs["iMakInventory_Cycle"]
    assert rec["open"] is None
    assert rec["done"][-1]["min"] == 95
    assert W.average_minutes(rec) == 95


def test_absurd_durations_are_not_kept():
    """26時間のような桁のおかしい記録は平均を壊すので残さない。"""
    start = datetime.datetime(2026, 9, 15, 13, 0, 0)
    runs = W.update_runs({}, {"iMakInventory_Cycle": start}, start)
    runs = W.update_runs(runs, {}, start + datetime.timedelta(hours=26))
    assert runs["iMakInventory_Cycle"]["done"] == []


def test_shows_end_estimate_while_running():
    runs = {"iMakInventory_Cycle": {"open": None, "done": [{"min": 100}, {"min": 80}]}}
    started = datetime.datetime(2026, 9, 16, 14, 30, 0)
    rows = W.status(runs, {"iMakInventory_Cycle": started}, {}, NOW)
    r = [x for x in rows if x["name"] == "iMakInventory_Cycle"][0]
    assert r["running"] and r["avg_min"] == 90
    assert r["eta"] == "16:00" and r["left_min"] == 60
    assert "巡回中 14:30〜" in W.headline(rows, NOW) and "終了めやす 16:00" in W.headline(rows, NOW)


def test_shows_next_start_when_idle():
    runs = {"iMakInventory_Cycle": {"open": None, "done": [{"min": 90}]}}
    nxt = {"iMakInventory_Cycle": datetime.datetime(2026, 9, 16, 19, 30, 0)}
    rows = W.status(runs, {}, nxt, NOW)
    line = W.headline(rows, NOW)
    assert "次の巡回 19:30" in line and "4.5時間" in line and "約90分" in line


def test_console_records_even_with_the_window_closed():
    """画面を閉じている間の巡回も記録する (でないと平均がいつまでも出ない)。"""
    src = open(os.path.join(HQ, "console", "server.py"), encoding="utf-8").read()
    assert "def _watcher_loop():" in src
    assert "threading.Thread(target=_watcher_loop, daemon=True).start()" in src
    assert '"/api/watcher"' in src
