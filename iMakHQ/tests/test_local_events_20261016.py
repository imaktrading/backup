# -*- coding: utf-8 -*-
"""2026-10-16 ユーザー「アメリカの祝日・給料日・〇〇祭・スーパーボウル…UK/AU/CA も。出品数をいつもより多くしてもいいかも、とか」"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))


def test_black_friday_week():
    import local_events as L
    ev = L.upcoming(dt.date(2026, 11, 24), 7)
    names = [(x["date"], x["country"], x["name"]) for x in ev]
    assert ("2026-11-26", "US", "感謝祭") in names
    assert ("2026-11-27", "ALL", "ブラックフライデー") in names
    assert ("2026-11-30", "ALL", "サイバーマンデー") in names
    assert not any(n.startswith("祝日") and d == "2026-11-26" and c == "US" for d, c, n in names)   # 行事と祝日が重なれば行事だけ


def test_super_bowl_is_second_sunday_of_feb():
    import local_events as L
    assert any(d == dt.date(2027, 2, 14) and n == "スーパーボウル" for d, c, n, _ in L.shopping_events(2027))


def test_paydays_month_end_workday():
    import local_events as L
    p = {(d, c) for d, c, n, _ in L.paydays(2026, 10)}
    assert (dt.date(2026, 10, 30), "UK") in p and (dt.date(2026, 10, 15), "US") in p    # 10/31 は土曜 → 30日(金)


def test_mail_subject_is_daily_report():
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools", "pdca_daily_mail.py"),
               encoding="utf-8").read()
    assert 'subject = (f"Daily Report ' in src and "local_events_next7" in src
