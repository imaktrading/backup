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
