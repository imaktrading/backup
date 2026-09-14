# -*- coding: utf-8 -*-
"""手で落とすレポートの守り (2026-09-14)。

- 広告レポートの期間は DL 時の選び方で変わり、ファイル名にも出ない。7/23 は 3日分、9/01 は 1日分で、
  9/02・9/04 のファネルは NO_SEARCH 277件 (90日分の 9/06 では 2件) になった → 期間を読んで 85日未満は止める
- 判定は1回で 1〜2% しか動かない → 古さの線を 4日 → 7日 (週1の DL で毎晩回る)
- 未落札レポートの名前が inactive-listings に変わった → 新旧どちらでも一番新しい方
- 「売れた分を補充」がデスクトップしか見ず、reports に置いた注文レポートで 0件だった
"""
import datetime as dt
import os
import sys

import pytest

HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HQ, "tools"))

import listing_funnel as LF  # noqa: E402
import sold_restock_worklist as W  # noqa: E402

REPORTS = r"C:/dev/iMak_data/seller_hub/reports"


def _promoted(path, start, end):
    path.write_text("\ufeffSome details are not available for inactive listings and campaigns.\n"
                    "Start date,End date,Campaign name,Item ID,Organic Impressions\n"
                    f'"{start}","{end}",c,358000000001,10\n', encoding="utf-8")
    return str(path)


def test_period_is_read_from_the_file(tmp_path):
    p = _promoted(tmp_path / "a.csv", "Jun 15, 2026", "Sep 12, 2026")
    assert LF.promoted_period(p) == (dt.date(2026, 6, 15), dt.date(2026, 9, 12), 90)
    short = _promoted(tmp_path / "b.csv", "Aug 31, 2026", "Sep 01, 2026")
    assert LF.promoted_period(short)[2] == 2 < LF.PROMOTED_MIN_DAYS


def test_no_period_columns_reads_as_none(tmp_path):
    p = tmp_path / "c.csv"
    p.write_text("Item ID,Organic Impressions\n1,2\n", encoding="utf-8")
    assert LF.promoted_period(str(p)) is None


@pytest.mark.parametrize("folder,days", [("20260901", 2), ("20260723", 4), ("20260914", 90)])
def test_real_reports_show_the_short_downloads(folder, days):
    d = os.path.join(REPORTS, folder)
    f = LF.find_file(d, "*promoted-listing*report*.csv") if os.path.isdir(d) else None
    if not f:
        pytest.skip("実機のレポートが無い")
    assert LF.promoted_period(f)[2] == days


def test_main_stops_on_a_short_period():
    src = open(LF.__file__, encoding="utf-8").read()
    assert "_pp[2] < PROMOTED_MIN_DAYS" in src and "期間 90日" in src
    assert LF.PROMOTED_MIN_DAYS == 85
    assert LF.STALE_REPORT_DAYS == 7


def test_unsold_report_new_name_wins_when_newer(tmp_path):
    old, new = tmp_path / "20260905", tmp_path / "20260914"
    old.mkdir()
    new.mkdir()
    (old / "eBay-unsold-listings-report-2026-09-05-1.csv").write_text("x", encoding="utf-8")
    (new / "eBay-inactive-listings-report-2026-09-13-2.csv").write_text("x", encoding="utf-8")
    got = LF.find_newest(str(tmp_path), ("*unsold-listings*.csv", "*inactive-listings*.csv"))
    assert os.path.basename(got).startswith("eBay-inactive-listings-report-2026-09-13")
    assert LF.find_newest(str(tmp_path), ("*nothing*.csv",)) is None


def test_orders_report_is_found_in_the_reports_folder(tmp_path):
    reports, desk = tmp_path / "reports", tmp_path / "desk"
    (reports / "20260914").mkdir(parents=True)
    desk.mkdir()
    (desk / "ebay-all-orders-report-2026-09-01-1.csv").write_text("x", encoding="utf-8")
    (reports / "20260914" / "ebay-all-orders-report-2026-09-13-2.csv").write_text("x", encoding="utf-8")
    got = W._find_desk_report([(str(reports), True), (str(desk), False)])
    assert got.endswith("ebay-all-orders-report-2026-09-13-2.csv")


def test_orders_report_date_formats():
    assert W.report_day("ebay-all-orders-report-2026-09-13-12345685590.csv") == dt.date(2026, 9, 13)
    assert W.report_day("eBay-OrdersReport-Sep-13-2026-23_07_00-0700-11334292920.csv") == dt.date(2026, 9, 13)
    assert W.report_day("orders.csv") is None
