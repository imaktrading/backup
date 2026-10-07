"""Terapeak の画面がドルの値に「¥」を付けて出すようになった (2026-10-07)。記号を外してドルとして読む。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import market_ledger as M  # noqa: E402


def test_money_reads_yen_marked_dollars():
    assert M._money("¥81") == 81.0
    assert M._money("¥1,234.5") == 1234.5
    assert M._money("$1,362.50") == 1362.5
    assert M._money("") is None and M._money(None) is None
