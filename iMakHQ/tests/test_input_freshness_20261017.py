"""入力の鮮度点検 (2026-10-17 ユーザー「不具合が出て気づくまでの期間が長いね」)。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import input_freshness as F  # noqa: E402


def test_old_traffic_report_is_red():
    # 10/06 の物を 10/17 に使っていた = 264時間前 → 赤
    r = F.judge("トラフィックレポート", 0, 36, 264 * 3600)
    assert r["stale"] and "264" in r["note"]


def test_fresh_is_not_red_and_missing_is_red():
    assert not F.judge("x", 100, 36, 100 + 3600)["stale"]
    assert F.judge("x", None, 36, 0)["stale"]


def test_summary_names_the_stale_ones():
    s = F.summary_line([{"name": "A", "stale": True, "note": "5時間前"}, {"name": "B", "stale": False, "note": ""}])
    assert "古い 1件" in s and "A (5時間前)" in s and "B" not in s
