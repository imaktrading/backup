# -*- coding: utf-8 -*-
"""棚② の件数の横に金額を出す (2026-09-28)。

ユーザー「棚②が10件と表示されているけど、金額も表示して」。
"""
import os
import sys

HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HQ, "console"))

import server as S  # noqa: E402


def test_shelf_note_shows_amount_target_and_max():
    p = {"picked": 10, "amount": 5046.04, "target": 4009.93,
         "max_picked": 465, "max_amount": 473473.84}
    assert S.shelf_note(p) == "空く額 $5,046 (今日の目標 $4,010)\n落とせる対象の全部 (上限・落とすべき量ではない): 465件 $473,474"


def test_shelf_note_without_max():
    assert S.shelf_note({"amount": 120.4, "target": 100}) == "空く額 $120 (今日の目標 $100)"


def test_tip_is_not_cut_at_160():
    # ユーザー「ヒントテキストの最後が見切れてる」: 説明を 160字で切っていた (棚② は172字)
    src = open(os.path.join(HQ, "console", "server.py"), encoding="utf-8").read()
    assert '"tip": (s.get("tip") or "")[:160]' not in src
