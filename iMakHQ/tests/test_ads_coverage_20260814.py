"""広告カバレッジ突合の純関数テスト (2026-08-14).

実測 (2026-08-14 初回): live 4,343件のうち広告に入っていたのは 1,843件 (42%)。
**2,500件は広告が一切当たっていない**。画面では追えなかった数字。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import ads_coverage as ac  # noqa: E402


def test_uncovered_is_live_minus_promoted():
    r = ac.coverage({"1", "2", "3"}, {"2"})
    assert r["live"] == 3
    assert r["covered"] == 1
    assert r["uncovered"] == ["1", "3"]


def test_stale_is_promoted_minus_live():
    """終了した listing がキャンペーンに残っているのを検出する."""
    r = ac.coverage({"1"}, {"1", "9"})
    assert r["stale_in_campaign"] == ["9"]
    assert r["uncovered"] == []


def test_full_coverage_reports_zero_uncovered():
    r = ac.coverage({"1", "2"}, {"1", "2"})
    assert r["uncovered"] == []
    assert r["covered"] == 2


def test_empty_live_does_not_crash():
    r = ac.coverage(set(), {"1"})
    assert r["live"] == 0
    assert r["covered"] == 0
    assert r["stale_in_campaign"] == ["1"]


def test_ids_are_compared_as_strings():
    """listingId は API が str、live キャッシュのキーも str。型で取りこぼさない."""
    r = ac.coverage({"123"}, {"123"})
    assert r["covered"] == 1


# ---- ★サイトを揃えずに突合しない (2026-08-14 の誤報告の再発防止) ----
# 初回、US のキャンペーンだけ集めて live 全件 (US + ミラー GB/AU/CA) と引き算し、
# 「2,500件が未広告」と報告した。実際はミラー分が各自のサイトのキャンペーンに入っており、
# 未広告は 11件だった。母数と分子のサイトを必ず合わせる。

def test_live_is_split_by_marketplace_via_currency():
    live = {
        "1": {"cur": "USD"}, "2": {"cur": "GBP"},
        "3": {"cur": "AUD"}, "4": {"cur": "CAD"}, "5": {"cur": "EUR"},
    }
    got = ac.split_live_by_marketplace(live)
    assert got["EBAY_US"] == {"1"}
    assert got["EBAY_GB"] == {"2"}
    assert got["EBAY_AU"] == {"3"}
    assert got["EBAY_CA"] == {"4"}
    assert got["EBAY_DE"] == {"5"}


def test_unknown_currency_is_bucketed_not_dropped():
    """未知通貨を黙って捨てると、また母数がズレる。'?' に出して見えるようにする."""
    got = ac.split_live_by_marketplace({"9": {"cur": "JPY"}, "8": {}})
    assert got["?"] == {"8", "9"}


def test_mirror_listing_is_not_counted_as_us_uncovered():
    """ミラー(GBP)の出品を US の未広告に数えない — 誤報告そのものの再現."""
    live = {"us1": {"cur": "USD"}, "gb1": {"cur": "GBP"}}
    by_mkt = ac.split_live_by_marketplace(live)
    us = ac.coverage(by_mkt["EBAY_US"], {"us1"})      # US キャンペーンには us1 だけ
    assert us["uncovered"] == [], "ミラー分が US の未広告に混ざっている"
