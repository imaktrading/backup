# -*- coding: utf-8 -*-
"""月の利益から「損失」タブ (仕入れ間違い等) を引く (2026-10-13 ユーザー「こういうミスも含めよう」)。"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import pdca_daily_mail as M  # noqa: E402


def test_loss_rows():
    rows = [["日付", "内容", "金額"], ["2026/10/09", "PSA7 間違い", "4,830"], ["", "空", "1"], ["2026/10/10", "x", "abc"]]
    out = M.loss_rows(rows)
    assert out == [{"date": dt.date(2026, 10, 9), "what": "PSA7 間違い", "amount": 4830.0}]


def test_month_summary_subtracts_loss_not_count():
    s = [{"date": dt.date(2026, 10, 3), "profit": 10000, "confirmed": True},
         {"date": dt.date(2026, 10, 5), "profit": 2000, "confirmed": False}]
    L = [{"date": dt.date(2026, 10, 9), "what": "PSA7", "amount": 4830}]
    ms = M.month_summary(s, dt.date(2026, 10, 13), 100000, L)
    assert ms["profit"] == 12000 - 4830 and ms["fixed"] == 10000 - 4830 and ms["tmp"] == 2000
    assert ms["n"] == 2 and ms["unit"] == 6000 and ms["loss"] == 4830
    ms0 = M.month_summary(s, dt.date(2026, 10, 13), 100000)
    assert ms0["profit"] == 12000 and ms0["loss"] == 0
