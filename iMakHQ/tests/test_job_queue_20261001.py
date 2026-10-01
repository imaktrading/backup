"""定期処理の順番待ち (job_queue) の純関数のテスト。

2026-10-01 ユーザー確定: 時刻ではなく「間隔と期限」と PC の空き・余力で流す。
重い処理は同時に1本、軽い処理は余力があれば並べる。期限切れは黙らずに出す。
"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import job_queue as Q  # noqa: E402

NIGHT = {"name": "night", "every_hours": 20, "window": [22, 6], "need_idle_min": 10,
         "deadline_hour": 7, "heavy": True}
PSA = {"name": "psa", "every_hours": 20, "window": [22, 7], "need_idle_min": 10,
       "deadline_hour": 9, "heavy": True}
RAW = {"name": "raw", "every_hours": 20, "need_idle_min": 5, "heavy": False}
BAK = {"name": "bak", "every_hours": 20, "wait_for": ["night"], "deadline_hour": 8, "heavy": False}
JOBS = [NIGHT, PSA, RAW, BAK]


def at(h, m=0, d=2):
    return dt.datetime(2026, 10, d, h, m)


def test_in_window_wraps_midnight():
    assert Q.in_window(23, [22, 6]) and Q.in_window(3, [22, 6])
    assert not Q.in_window(6, [22, 6]) and not Q.in_window(15, [22, 6])
    assert Q.in_window(10, None) and Q.in_window(10, [9, 17]) and not Q.in_window(17, [9, 17])


def test_is_due_by_interval():
    assert Q.is_due(NIGHT, None, at(22))
    assert not Q.is_due(NIGHT, {"last_ok": "2026-10-02T03:00:00"}, at(22))
    assert Q.is_due(NIGHT, {"last_ok": "2026-10-01T23:00:00"}, at(22))


def test_pick_one_heavy_at_a_time_by_deadline_and_light_alongside():
    got = Q.pick(JOBS, {}, set(), at(23), idle_min=30, mem_pct=30, cpu_pct=10)
    assert got[0] == "night"                 # 期限が早い重い処理が先
    assert "psa" not in got                  # 重いのは同時に1本
    assert "raw" in got                      # 軽いのは並べる
    assert "bak" not in got                  # 夜の束を待つ (今起動する = 動いている扱いではないが)


def test_pick_waits_for_running_and_respects_window_idle_load():
    assert "bak" not in Q.pick(JOBS, {}, {"night"}, at(3), 30, 30, 10)
    assert "psa" not in Q.pick(JOBS, {}, {"night"}, at(3), 30, 30, 10)        # 重い処理が動いている
    assert Q.pick([NIGHT], {}, set(), at(15), 30, 30, 10) == []              # 時間帯の外
    assert Q.pick([NIGHT], {}, set(), at(23), 3, 30, 10) == []               # 触っている
    assert Q.pick(JOBS, {}, set(), at(23), 30, 80, 10) == []                 # メモリの余力なし
    assert Q.pick(JOBS, {}, set(), at(23), 30, 30, 90) == []                 # CPU の余力なし


def test_pick_skips_disabled_and_not_due():
    st = {"night": {"last_ok": "2026-10-02T22:30:00"}}
    got = Q.pick([dict(NIGHT, enabled=True), dict(RAW, enabled=False)], st, set(), at(23), 30, 30, 10)
    assert got == []


def test_overdue_only_after_deadline_while_still_due():
    assert Q.overdue(NIGHT, {"last_ok": "2026-10-01T05:00:00"}, at(8))
    assert not Q.overdue(NIGHT, {"last_ok": "2026-10-02T01:00:00"}, at(8))   # 済んでいる
    assert not Q.overdue(NIGHT, {"last_ok": "2026-10-01T05:00:00"}, at(5))   # まだ期限前
    assert not Q.overdue(RAW, None, at(12))                                    # 期限の無い処理
