# -*- coding: utf-8 -*-
"""2026-10-15 ユーザー確定「日本時間の0時から24時を一日とする」: 毎朝のメールの新規・取下げを eBay から前日 0〜24時で取る。"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))


def test_jst_window_is_midnight_to_midnight():
    import pdca_daily_mail as M
    a, b = M.jst_window(dt.date(2026, 10, 15), dt.date(2026, 10, 15))
    assert (a, b) == ("2026-10-14T15:00:00.000Z", "2026-10-15T15:00:00.000Z")


def test_ebay_moves_counts_us_only_and_ended_only():
    import pdca_daily_mail as M

    def post(call, inner):
        start = "<StartTimeFrom>" in inner
        items = ([("1", "US", "PSA 10 Pikachu", "Active"), ("2", "UK", "PSA 10 Pikachu", "Active"), ("3", "US", "G-Shock", "Active")]
                 if start else [("4", "US", "PSA 10 x", "Completed"), ("5", "US", "y", "Active"), ("6", "Canada", "z", "Completed")])
        body = "".join(f"<Item><ItemID>{i}</ItemID><Site>{s}</Site><Title>{t}</Title><SellingStatus><ListingStatus>{st}</ListingStatus></SellingStatus></Item>"
                       for i, s, t, st in items)
        return "<Ack>Success</Ack>" + body + "<PaginationResult><TotalNumberOfPages>1</TotalNumberOfPages></PaginationResult>"
    mv = M.ebay_moves(dt.date(2026, 10, 15), post, live=1000)
    assert mv["new"] == 2 and mv["new_cat"] == {"PSA10": 1, "他": 1}
    assert mv["ended"] == 1                        # Active (GTC の更新) と US 以外は数えない
    assert mv["src"] == "ebay" and mv["live"] == 1000
