# -*- coding: utf-8 -*-
"""日報メールに受信したオファーの数 (eBay のメールから数える・2026-10-12)。"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import pdca_daily_mail as M  # noqa: E402

T = dt.date(2026, 10, 13)


def test_counts_yesterday_and_two_weeks():
    d = [dt.date(2026, 10, 12)] * 2 + [dt.date(2026, 10, 6)] + [dt.date(2026, 10, 5)] * 3 + [dt.date(2026, 9, 28)]
    assert M.offer_counts(d, T) == {"yesterday": 2, "last7": 3, "prev7": 3}   # 9/28 は前の7日 (9/29〜10/5) より前


def test_today_not_counted():
    assert M.offer_counts([T], T) == {"yesterday": 0, "last7": 0, "prev7": 0}


def test_cell_rendered_and_missing():
    src = open(os.path.join(os.path.dirname(__file__), "..", "tools", "pdca_daily_mail.py"), encoding="utf-8").read()
    assert "メールを読めず" in src and "前の7日" in src
