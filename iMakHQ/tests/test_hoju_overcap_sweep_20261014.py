"""補に入れた後で値上げされ、仕入上限を超えた補を夜の掃除で外す (2026-10-14 ユーザー「そだね」)。"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
import psa_hoju_fill as H  # noqa: E402


def test_plan_picks_only_aux_over_cap():
    vals = [["h"] * 40, [""] * 40, [""] * 40]
    vals[1][H.AUX0] = "https://a/1"
    vals[1][H.AUX0 + 1] = "https://a/2"
    vals[2][H.AUX0] = "https://a/3"
    prices = {H._norm_url("https://a/1"): 950000, H._norm_url("https://a/2"): 12000, H._norm_url("https://a/3"): 70000}
    plan = H.overcap_aux_plan(vals, prices, lambda p: p > 70000)
    assert plan == {2: ["https://a/1"]}


def test_nightly_batch_runs_the_sweep():
    src = open(os.path.join(HERE, "..", "tools", "run_hoju_search.bat"), encoding="ascii").read()
    assert "psa_hoju_fill.py sweep-overcap" in src
