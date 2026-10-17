# -*- coding: utf-8 -*-
"""B-20261017-009: ハントは交互・落ちたら同じ方・同じ夜の PSA の情報取りより先・自動の Chrome が残っていたら始めない。"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import job_queue as J            # noqa: E402
import run_hunt_alternate as H   # noqa: E402

NIGHT = dt.datetime(2026, 10, 17, 22, 30)
JOBS = [
    {"name": "night_bundle", "every_hours": 20, "window": [22, 6], "deadline_hour": 7, "heavy": True},
    {"name": "psa_cache_warm", "every_hours": 20, "window": [22, 7], "deadline_hour": 9, "heavy": True},
    {"name": "hunt", "every_hours": 48, "window": [22, 6], "heavy": True, "order": 0, "need_no_chrome": True},
]


def test_alternates_and_resumes():
    assert H.next_kind({}) == ("treasure", False)
    assert H.next_kind({"last": "treasure"}) == ("chara", False)
    assert H.next_kind({"last": "chara"}) == ("treasure", False)
    assert H.next_kind({"last": "treasure", "running": "treasure"}) == ("treasure", True)


def test_hunt_goes_first_among_heavy():
    assert J.pick(JOBS, {}, set(), NIGHT, 60, 40, 10) == ["hunt"]


def test_hunt_waits_while_driver_chrome_left():
    # 自動の Chrome が残っている夜はハントを飛ばし、他の重い処理は今までどおり
    assert J.pick(JOBS, {}, set(), NIGHT, 60, 40, 10, driver_chrome=2) == ["night_bundle"]


def test_without_order_old_sequence_kept():
    jobs = [j for j in JOBS if j["name"] != "hunt"]
    assert J.pick(jobs, {}, set(), NIGHT, 60, 40, 10) == ["night_bundle"]


def test_driver_count_reads_powershell(monkeypatch):
    class R:
        stdout = "3\n"
    monkeypatch.setattr(J.subprocess, "run", lambda *a, **k: R())
    assert J.driver_chrome_count() == 3
