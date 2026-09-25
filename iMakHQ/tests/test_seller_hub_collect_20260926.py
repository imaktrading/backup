"""ダウンロード フォルダから拾うのはファネルの材料になるレポートだけ (2026-09-26)。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
from seller_hub_collect import is_report  # noqa: E402


def test_the_five_reports_are_picked():
    for n in ("eBay-all-active-listings-report-2026-09-13-13327686857.csv",
              "eBay-inactive-listings-report-2026-09-13-11334292421.csv",
              "ebay-all-orders-report-2026-09-13-12345685590.csv",
              "eBay-promoted-listing-general-listing-report-2026-09-13-12345685681.csv",
              "Listing quality report for imax-64 - US - 09_12_2026 07-30 PST.xlsx"):
        assert is_report(n), n


def test_other_files_and_partial_downloads_are_left():
    for n in ("tcg_upload_20260926.csv", "photo.jpg",
              "eBay-all-active-listings-report-2026-09-26-1.csv.crdownload"):
        assert not is_report(n), n
