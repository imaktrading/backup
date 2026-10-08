# -*- coding: utf-8 -*-
"""② の締めの1行: 送る前に外した行も「見送り」に数え、あれば「正常」と書かない (2026-10-08)。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
import psa_restock_build as B


def test_skipped_rows_are_counted_and_not_normal():
    s = B.summary_line(0, 0, 0, [("358514312870", "上げられない台帳に載っている")], [])
    assert "見送り 1件" in s
    assert "正常" not in s


def test_all_sent_is_normal():
    s = B.summary_line(3, 0, 0, [], [])
    assert s.endswith("✅ 正常")


def test_ng_wins():
    s = B.summary_line(1, 0, 1, [("x", "y")], ["820000000000"])
    assert "⚠️要対応 1件" in s and "見送り 2件" in s
