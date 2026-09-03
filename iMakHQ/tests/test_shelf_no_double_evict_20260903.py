# -*- coding: utf-8 -*-
"""同じ日に押すたび同じ額が落ちるのを止める (2026-09-03)。

## 実害
目標は「今日の出品額」なので、空欄で2回押したら **2回とも同じ額が落ちた**
(実測: $14,939 + $15,624 = 出品額の2倍)。出したぶんは1回落とせば釣り合うので、
2回目以降は落としすぎ。

今日すでに落とした額を覚えて、残りだけを目標にする。
"""
import os
import sys
import datetime

_HQ_TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
if _HQ_TOOLS not in sys.path:
    sys.path.insert(0, _HQ_TOOLS)

import shelf_evict as SE  # noqa: E402


def test_second_press_only_targets_the_remainder():
    assert SE.remaining_target(14459, 0) == 14459
    assert SE.remaining_target(14459, 14939) == 0        # もう足りている
    assert SE.remaining_target(20000, 5000) == 15000


def test_never_negative():
    assert SE.remaining_target(1000, 99999) == 0


def test_ledger_round_trip(tmp_path):
    p = tmp_path / "ev.json"
    day = datetime.date(2026, 9, 3)
    assert SE.evicted_today_amount(day, str(p)) == 0.0
    SE.remember_evicted(14939, day, str(p))
    SE.remember_evicted(15624, day, str(p))
    assert SE.evicted_today_amount(day, str(p)) == 30563.0
    # 別の日は混ざらない
    assert SE.evicted_today_amount(datetime.date(2026, 9, 4), str(p)) == 0.0


def test_amount_flag_still_wins():
    """金額を指定した時は、今日の残りに関係なくその額まで落とす。"""
    src = open(os.path.join(_HQ_TOOLS, "shelf_evict.py"), encoding="utf-8").read()
    i = src.index("target = a.amount")
    assert "if a.amount is not None:" in src[i - 80:i + 40]
