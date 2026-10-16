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


def test_provisional_ship_for_psa_until_entered():
    """2026-10-16 ユーザー: 送料が未入力の PSA は US 4,000円・US 以外 1,100円を仮に引く。入れば実額"""
    import pdca_daily_mail as M
    head = [""] * 26
    def row(country, ship, title="PSA 10 Pikachu"):
        r = [""] * 26
        r[1], r[2], r[4], r[5], r[6], r[12], r[14], r[15], r[21], r[25] = "1", title, "2026/10/15", country, "$100", "5000", ship, "¥8,000", "TRUE", "未発送"
        return r
    got = M.sales_rows([head, row("United States", ""), row("United Kingdom", ""), row("United States", "3500"),
                        row("United States", "", "UNIQLO UT Tee")])
    assert [g["profit"] for g in got] == [4000, 6900, 8000, 8000]
    assert [g["ship_provisional"] for g in got] == [4000, 1100, 0, 0]
    assert not got[0]["confirmed"] and got[2]["confirmed"]


def test_insight_facts_compares_weeks_and_lists_losses(monkeypatch):
    """2026-10-16 ユーザー「見たらわかることを書かれても。気付きとか注意とか」: 突き合わせの材料を渡す"""
    import pdca_daily_mail as M
    d = dt.date
    sales = [{"date": d(2026, 10, 14), "title": "A", "profit": -2000, "country": "US", "ship_provisional": 4000},
             {"date": d(2026, 10, 13), "title": "B", "profit": 6000, "country": "UK", "ship_provisional": 0},
             {"date": d(2026, 10, 3), "title": "C", "profit": 10000, "country": "US", "ship_provisional": 0}]
    ms = {"month": d(2026, 10, 1), "last": d(2026, 10, 14)}
    monkeypatch.setitem(sys.modules, "psa_hoju_fill", None)
    f = M.insight_facts(sales, ms, d(2026, 10, 15))
    assert f["sales_last7"] == {"n": 2, "avg_profit": 2000} and f["sales_prev7"]["n"] == 1   # 10/3 は前の7日 (10/1〜7)
    assert [x["title"] for x in f["month_loss_sales"]] == ["A"]
    assert f["month_provisional_ship_total"] == 4000
    assert "month_by_country" not in f and "month_by_weekday" not in f   # 当店の実績の偏りは渡さない (2026-10-16)


def test_comment_prompt_forbids_restating():
    import inspect
    import pdca_daily_mail as M
    src = inspect.getsource(M.ai_comment)
    assert "言い直さない" in src and "recent_comments" in src
