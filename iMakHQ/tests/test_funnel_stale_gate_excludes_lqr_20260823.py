"""レポート鮮度ガードから LQR を外す (2026-08-23).

Listing quality report は eBay が **週次でしか作らない**ので、他4本を今日落としても
必ず数日古い。それを含めて判定すると毎回 gate に引っかかり、`--force` が常用になって
gate の意味が消える (実際 8/23 に5本そろえても「最古4日前」で中断した)。
日次で取れる4本だけで見る。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

SRC = os.path.join(os.path.dirname(__file__), "..", "tools", "listing_funnel.py")


def _src():
    return open(SRC, encoding="utf-8").read()


def test_gate_does_not_include_quality_report():
    src = _src()
    assert "worst_report_age([f_active, f_unsold, f_promoted, f_orders])" in src, \
        "鮮度ガードに LQR が混ざっている (毎回 --force が要る形に戻っている)"


def test_quality_age_is_still_shown():
    """外すだけで隠さない。LQR が何日前かは表示する."""
    src = _src()
    assert "_lqr_age" in src
    assert "週次" in src, "なぜ数日古くて良いのかの説明が無い"


def test_gate_itself_is_kept():
    """ガードを消してはいない (古いレポートで走らせない目的は維持)."""
    src = _src()
    assert "STALE_REPORT_DAYS" in src
    assert "⛔ 中断: レポートが古いです" in src


def test_worst_report_age_ignores_none():
    import listing_funnel as lf
    assert lf.worst_report_age([None, None]) == 999
