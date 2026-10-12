# -*- coding: utf-8 -*-
"""売れ筋 × 補2本以下を、夜の探索と補充の目視で先に (2026-10-13・バリヤード CLK 013/032)。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import psa_hoju_fill as H  # noqa: E402


def _t(iid, key, n):
    return {"itemID": iid, "key": key, "n_backups": n}


def test_hot_first_keeps_order_inside_groups():
    ts = [_t("a", "k_cold", 0), _t("b", "k_hot", 3), _t("c", "k_hot", 2), _t("d", "k_cold", 1), _t("e", "k_hot", 0)]
    out, n = H.urgent_first(ts, {"k_hot": 5})
    assert [t["itemID"] for t in out] == ["c", "e", "a", "b", "d"]
    assert n == 2


def test_no_market_data_keeps_order():
    ts = [_t("a", "k1", 0), _t("b", "k2", 1)]
    out, n = H.urgent_first(ts, {})
    assert [t["itemID"] for t in out] == ["a", "b"] and n == 0


def test_wired_into_night_and_confirm():
    src = open(os.path.join(os.path.dirname(__file__), "..", "tools", "psa_hoju_fill.py"), encoding="utf-8").read()
    assert src.count("urgent_first(") >= 3          # 定義 + 夜 + 目視
    assert "先に探す" in src and "先に出す" in src
