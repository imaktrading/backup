# -*- coding: utf-8 -*-
"""昼に PC が起動し直しても夜間バッチの続きを走らせない (2026-09-29 ユーザー確定「夜だね」)。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import night_resume as R  # noqa: E402


def test_only_night_hours_resume():
    assert [h for h in range(24) if R.is_night(h)] == [0, 1, 2, 3, 4, 5, 6, 21, 22, 23]
