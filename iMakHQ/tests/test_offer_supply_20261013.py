# -*- coding: utf-8 -*-
"""オファーの表に今買える安い仕入元 (上位3本) と条件OK最安での利益 (B-20261013-003)。"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import offer_calc as O  # noqa: E402
import psa_sold_cheapest as P  # noqa: E402


def test_supply_summary_top3_and_best_ok():
    cands = [{"src": "メルカリ", "price": 4666, "url": "u1", "channel": "mercari", "buyable": True, "version": "番号未確認",
              "ship": "送料込み", "reviews": 500},
             {"src": "仕入元", "price": 4777, "url": "u2", "buyable": True},
             {"src": "スニダン", "price": 5000, "url": "u3", "buyable": False},
             {"src": "補1", "price": 5999, "url": "u4", "buyable": True}]
    s = O.supply_summary(cands, P.marks_of)
    assert [c["price"] for c in s["top"]] == [4666, 4777, 5999]          # 売り切れは出さない
    assert s["best_ok"] == 4777 and s["n_ok"] == 2
    assert s["top"][0]["marks"] == ["番号未確認"]


def test_stale():
    now = dt.datetime(2026, 10, 13, 17, 0)
    assert O.supply_stale(None, now)
    assert O.supply_stale({"at": "2026-10-13T09:00:00"}, now)
    assert not O.supply_stale({"at": "2026-10-13T16:00:00"}, now)


def test_find_for_extracted():
    assert callable(P.find_for)
    src = open(os.path.join(os.path.dirname(__file__), "..", "tools", "psa_sold_cheapest.py"), encoding="utf-8").read()
    assert "    done = find_for(orders)" in src
