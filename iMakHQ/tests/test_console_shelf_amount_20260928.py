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
    # ★2026-10-05 ユーザー「上限は不要」: 今日の目標額は無くなった。押すとルールで落とす物を全部落とす
    p = {"picked": 465, "amount": 473473.84, "max_picked": 465, "max_amount": 473473.84}
    assert S.shelf_note(p) == "空く額 $473,474 (ルールで落とす物を全部)"
    assert "今日の目標" not in S.shelf_note(p)


def test_shelf_note_without_max():
    assert S.shelf_note({"amount": 120.4}) == "空く額 $120 (ルールで落とす物を全部)"


def test_tip_is_not_cut_at_160():
    # ユーザー「ヒントテキストの最後が見切れてる」: 説明を 160字で切っていた (棚② は172字)
    src = open(os.path.join(HQ, "console", "server.py"), encoding="utf-8").read()
    assert '"tip": (s.get("tip") or "")[:160]' not in src
