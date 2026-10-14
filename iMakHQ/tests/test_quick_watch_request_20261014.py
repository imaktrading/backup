"""監視くんの短い巡回 QUICK に「すぐ見て」と頼む (2026-10-14 ブラボー GO B-20261014-008)。"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
import quick_watch_request as Q  # noqa: E402


def test_pending_is_rows_with_empty_state():
    rows = [["itemID", "理由", "依頼時刻", "依頼者", "状態", "処理時刻"],
            ["111", "急ぐ", "t", "出品くん", "", ""],
            ["222", "急ぐ", "t", "出品くん", "済", "t2"]]
    assert Q.pending_ids(rows) == {"111"}


def test_build_rows_skips_pending_and_duplicates():
    out = Q.build_rows(["111", "333", "333", ""], Q.R_AUX, {"111"}, "now")
    assert out == [["333", "補を書いた", "now", "出品くん", "", ""]]


def test_hoju_confirm_asks_after_writing():
    src = open(os.path.join(HERE, "..", "tools", "psa_hoju_fill.py"), encoding="utf-8").read()
    assert "quick_watch_request" in src and "_qw.R_AUX" in src
