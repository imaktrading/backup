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


def test_churn_counts_and_puts_first_regardless_of_backups():
    import datetime as dt
    nb = {"u1": {"why": "売り切れ (監視くん)", "at": "2026-10-10T09:00"},
          "u2": {"why": "売り切れ (監視くん)", "at": "2026-10-11T09:00"},
          "u3": {"why": "売り切れ", "at": "2026-08-01T09:00"},          # 30日より前
          "u4": {"why": "オークション", "at": "2026-10-11T09:00"}}
    aux = [{"url": "u1", "row": 5}, {"url": "u2", "row": 5}, {"url": "u3", "row": 5}, {"url": "u4", "row": 5}]
    ch = H.sold_out_churn(nb, aux, {5: "iid5"}, dt.date(2026, 10, 13))
    assert ch == {"iid5": 2}
    ts = [_t("a", "k", 0), _t("iid5", "k_cold", 4)]
    out, n = H.urgent_first(ts, {}, churn=ch, churn_min=2)
    assert [t["itemID"] for t in out] == ["iid5", "a"] and n == 1


def test_cap_keeps_rest_in_place():
    ts = [_t("a", "c", 0), _t("h1", "h", 0), _t("b", "c", 0), _t("h2", "h", 0), _t("h3", "h", 0)]
    out, n = H.urgent_first(ts, {"h": 1}, cap=2)
    assert [t["itemID"] for t in out] == ["h1", "h2", "a", "b", "h3"] and n == 2


def test_dry_streak_with_few_backups_goes_first():
    ts = [_t("a", "k", 0), _t("d1", "k", 0), _t("d2", "k", 4)]
    dry = {"d1": {"streak": 5}, "d2": {"streak": 5}}
    out, n = H.urgent_first(ts, {}, dry=dry)
    assert [t["itemID"] for t in out] == ["d1", "a", "d2"] and n == 1


def test_kagoya_does_not_rest_dry_listings():
    src = open(os.path.join(os.path.dirname(__file__), "..", "tools", "kagoya_offload.py"), encoding="utf-8").read()
    assert "lambda e, t: False" in src and "dry=_dry" in src
