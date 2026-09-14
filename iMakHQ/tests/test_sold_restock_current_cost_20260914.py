# -*- coding: utf-8 -*-
"""売れた分を補充: 今の仕入値で、発送済みの分だけ (2026-09-14)。

ユーザー「当然、今の仕入れ値で押さないとあかんやろ」。
- 監視くんは巡回ごとに M を「仕入元と補URLのうち生きている最安」で書き直す。巡回が新しく売切でなければ
  台帳の N が今の仕入値。一律「古い値」扱いにして毎回止まっていた
- 未発送の注文がある出品は、その仕入れがまだ終わっていないことがある → 数量を戻さない
"""
import datetime as dt
import os
import sys

HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HQ, "tools"))
sys.path.insert(0, r"C:\dev\iMak\iMakeBayAPI")

import sold_restock as R  # noqa: E402

NOW = dt.datetime(2026, 9, 14, 16, 0)


def _row(checked="2026/9/14 4:21:02", sold=""):
    r = [""] * 40
    r[R.COL_CHECKED] = checked
    r[R.COL_SOLD] = sold
    return r


def test_recent_crawl_means_current_cost():
    assert R.row_cost_is_current(_row(), now=NOW)


def test_old_crawl_or_sold_supply_is_not_current():
    assert not R.row_cost_is_current(_row("2026/9/10 4:21:02"), now=NOW)
    assert not R.row_cost_is_current(_row(sold="○"), now=NOW)
    assert not R.row_cost_is_current(_row(""), now=NOW)
    assert not R.row_cost_is_current(_row("不明"), now=NOW)


def test_unshipped_order_blocks_restock():
    assert R.order_shipped({"Shipped On Date": "Sep-10-26"})
    paid = {"Shipped On Date": "", "Paid On Date": "Sep-12-26", "Total Price": "$294.98"}
    assert R.order_pending(paid)
    assert not R.order_pending(dict(paid, **{"Shipped On Date": "Sep-13-26"}))


def test_unpaid_or_refunded_order_is_not_pending():
    """実例: 8/23 G-SHOCK は未払い、7/24 G-SHOCK は全額返金 (Total Price £0.00)。仕入れは発生しない。"""
    assert not R.order_pending({"Shipped On Date": "", "Paid On Date": "", "Total Price": "$235.00"})
    assert not R.order_pending({"Shipped On Date": "", "Paid On Date": "Jul-24-26", "Total Price": "GB £0.00"})


def test_listing_sold_twice_with_one_unshipped_is_pending(monkeypatch):
    rows = {"358887214446": ("スプシ1", 1320, ["x"])}
    monkeypatch.setattr(R.W, "find_row", lambda sheets, sku, iid: rows.get(iid, (None, None, None)))
    want = [({"Item Number": "358887214446", "Shipped On Date": "", "Paid On Date": "Sep-12-26", "Total Price": "$294.98"}, "PSA"),
            ({"Item Number": "358887214446", "Shipped On Date": "Aug-26-26"}, "PSA")]
    assert R.pending_rows(want, []) == {("スプシ1", 1320)}


def test_main_checks_pending_before_sending():
    src = open(R.__file__, encoding="utf-8").read()
    i_pending = src.index("if (label, n) in pending:\n            print(")
    i_send = src.index('call = "RelistFixedPriceItem"')
    assert i_pending < i_send
