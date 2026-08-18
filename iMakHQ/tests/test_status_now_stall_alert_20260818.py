# -*- coding: utf-8 -*-
"""詰まった時だけ知らせる (2026-08-18 ユーザー判断).

「PDCA が回っているなら見えなくていい。ただし止まった時に気づける必要はある」。
一覧を増やすと読む手間が増えるだけなので、**閾値を超えた時だけ1行**出す。

今日見つけた3件 (出品結果メール / 補URL追記 / レビュー待ち) は、どれも壊れていたのではなく
**止まっていることが見えなかった** だけだった。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
from status_now import STALL_DAYS, stalled_lines  # noqa: E402

TODAY = "2026-08-18"


class TestQuietWhenMoving:
    def test_nothing_when_empty(self):
        assert stalled_lines([], TODAY) == []

    def test_nothing_when_recent(self):
        assert stalled_lines([{"updated_ts": "2026-08-17"}], TODAY) == []

    def test_nothing_just_under_the_threshold(self):
        assert stalled_lines([{"updated_ts": "2026-08-12"}], TODAY) == []


class TestSpeaksWhenStalled:
    def test_one_line_only(self):
        got = stalled_lines([{"updated_ts": "2026-08-01"}], TODAY)
        assert len(got) == 1 and got[0].startswith("⚠️")

    def test_counts_and_worst_age(self):
        got = stalled_lines([{"updated_ts": "2026-08-01"},
                             {"updated_ts": "2026-07-20"},
                             {"updated_ts": "2026-08-18"}], TODAY)[0]
        assert "2件" in got and "29日" in got

    def test_boundary_is_inclusive(self):
        assert stalled_lines([{"updated_ts": "2026-08-11"}], TODAY) != []

    def test_threshold_is_a_week(self):
        assert STALL_DAYS == 7


class TestNeverGuesses:
    def test_unreadable_dates_are_not_counted(self):
        rows = [{"updated_ts": ""}, {"updated_ts": "?"}, {}, None]
        assert stalled_lines(rows, TODAY) == []

    def test_bad_today_is_silent(self):
        assert stalled_lines([{"updated_ts": "2026-01-01"}], "") == []


class TestWiredIntoStatusNow:
    def test_printed_only_when_present(self):
        src = open(os.path.join(os.path.dirname(__file__), "..", "tools",
                                "status_now.py"), encoding="utf-8").read()
        assert "for ln in _stalled():" in src
        assert "常時表示しない" in src
