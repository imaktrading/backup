# -*- coding: utf-8 -*-
"""2026-10-17 ユーザー確定「各ボタンが自分の件数を責任を持って数える」:
押した時・終わった時に自分の分 / 件数の横に数えた時刻 (押すとそのボタンだけ) / 夜中4時に1回だけ全部。"""
import datetime as dt
import os
import sys

HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(HQ, "console"), HQ]


def test_night_recount_due_once_at_4am():
    import server as S
    d = dt.datetime(2026, 10, 17, 4, 5)
    assert S.night_recount_due(d, None, False)
    assert not S.night_recount_due(d, "2026-10-17", False)          # 今日はもうやった
    assert not S.night_recount_due(d, None, True)                    # 走行中は待つ
    assert not S.night_recount_due(dt.datetime(2026, 10, 17, 5, 0), None, False)


def test_jobs_carry_their_own_counted_time(monkeypatch):
    import server as S
    monkeypatch.setitem(S.STATE, "counts", {"hoju": {}})
    monkeypatch.setitem(S.STATE, "counts_at", "2026-10-17T00:00:00")
    monkeypatch.setitem(S.STATE, "counts_at_by", {"hoju": "2026-10-17T06:30:00"})
    jobs = {j["kind"]: j for j in S.get_jobs()["jobs"]}
    assert jobs["hoju_swap"]["counted_at"] == "2026-10-17T06:30:00"     # 自分の項目の時刻
    assert jobs["cull_end"]["counted_at"] == "2026-10-17T00:00:00"      # 無ければ全体の時刻


def test_screen_shows_time_and_recounts_only_that_button():
    src = open(os.path.join(HQ, "console", "static", "app.js"), encoding="utf-8").read()
    assert "data-recount" in src and 'post("/api/refresh", { kind:' in src
    ssrc = open(os.path.join(HQ, "console", "server.py"), encoding="utf-8").read()
    assert 'kwargs={"wait": True, "keys": _pk}' in ssrc                 # 押した時に自分の分
