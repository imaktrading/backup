# -*- coding: utf-8 -*-
"""ファネル分析のレポート鮮度ガード (listing_funnel の鮮度判定) — 古いと中断。"""
import importlib.util
import os

_LF = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "tools", "listing_funnel.py"))


def _load():
    spec = importlib.util.spec_from_file_location("listing_funnel_fresh", _LF)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_report_age_from_filename_ymd():
    lf = _load()
    # 2020-01-01 は十分古い (>1000日前)。ファイル名の日付を読む(mtime非依存)。
    assert lf._report_age_days("eBay-all-active-listings-report-2020-01-01.csv") > 1000


def test_report_age_from_filename_quality_mdy():
    lf = _load()
    # quality は MM_DD_YYYY 形式
    assert lf._report_age_days("Listing quality report 01_01_2020.xlsx") > 1000


def test_worst_report_age_picks_oldest():
    lf = _load()
    paths = ["a-2020-01-01.csv", "b-2099-01-01.csv", None]  # 2099は未来(負), Noneは無視
    # 最古(2020)の経過日数が最大として返る
    assert lf.worst_report_age(paths) == lf._report_age_days("a-2020-01-01.csv")


def test_stale_threshold_constant():
    lf = _load()
    assert lf.STALE_REPORT_DAYS >= 1   # 中断閾値が定義されている
