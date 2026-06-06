# -*- coding: utf-8 -*-
"""「既存メンテ」スプシ populator (existing_maint_dashboard) の純粋ロジック。"""
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "tools")))
import existing_maint_dashboard as emd  # noqa: E402


def _r(flags, **kw):
    d = {"flags": flags, "category": "Wristwatches", "price": "100",
         "sold_qty": "0", "sales90": "0", "watch": "0", "title": "T"}
    d.update(kw)
    return d


def test_funnel_summary_counts_flags():
    rows = [_r("RELIST|NO_SEARCH"), _r("RELIST|NO_CLICK"), _r("RESTOCK"), _r("CULL|OUT_OF_STOCK")]
    data = emd.build_funnel_summary(rows, "funnel_x.csv")
    # data[0]=サマリー行, data[1]=ヘッダ, data[2:]=flag行 (FLAG_META順)
    counts = {row[0]: row[1] for row in data[2:]}
    assert counts["RELIST"] == 2
    assert counts["NO_SEARCH"] == 1
    assert counts["NO_CLICK"] == 1
    assert counts["RESTOCK"] == 1
    assert counts["CULL"] == 1
    assert counts["OUT_OF_STOCK"] == 1
    assert counts["NO_CONVERT"] == 0
    assert "総listing 4" in data[0][0]


def test_restock_only_and_sorted_by_demand():
    rows = [
        _r("RESTOCK", title="lowdemand", sales90="0", watch="1"),
        _r("RESTOCK", title="hot", sold_qty="3", sales90="5", watch="9"),
        _r("RESTOCK", title="mid", sales90="2", watch="2"),
        _r("CULL", title="notrestock"),     # RESTOCK でない → 除外
    ]
    data, n = emd.build_restock(rows)
    assert n == 3
    titles = [row[5] for row in data[2:]]   # data[0]=サマリー,[1]=ヘッダ
    assert titles[0] == "hot"               # sold_qty 最大が先頭
    assert "notrestock" not in titles
