# -*- coding: utf-8 -*-
"""押したら片づく件数を出す — 出せていなければ機械が気づく (2026-09-10 ユーザー指示).

> 主旨理解している? 押したら作業できる残件数を表示して欲しいの

数え方を直すだけでは、また別の理由でズレる (同じボタンで4回起きた:
9/04 ff38dd1 / 9/07 b9575a2 / 9/10 4e26749 / 9/10 集合化)。
なので **押した後に本当に減ったか** を毎回突き合わせ、減っていなければ黙らない。
"""
import os
import sys

HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HQ)

import control_panel as CP          # noqa: E402


def test_reads_the_number_from_the_hint():
    NL = chr(10)
    assert CP.badge_number(NL + "残り 2件 — 今回 全部 目視します" + NL + "(候補 64件のうち)") == 2
    assert CP.badge_number(NL + "残り 15件 — 今回 15件 目視します (あと約7回)") == 15


def test_zero_is_zero_not_unknown():
    """「押しても0件」は 0。判らない (None) と混ぜない。"""
    assert CP.badge_number(chr(10) + "※押しても0件" + chr(10) + "(候補 64件のうち)") == 0


def test_unreadable_is_unknown():
    assert CP.badge_number("(残件 取得できず: HttpError)") is None
    assert CP.badge_number("") is None
    assert CP.badge_number(None) is None


def test_flags_when_the_press_changed_nothing():
    """1件と出ていて、押しても1件のまま = 表示が作業できる件数になっていない。"""
    assert CP.badge_did_not_move(1, 1) is True
    assert CP.badge_did_not_move(2, 3) is True      # 増えたのも「減っていない」


def test_does_not_flag_normal_progress():
    assert CP.badge_did_not_move(2, 1) is False
    assert CP.badge_did_not_move(1, 0) is False
    assert CP.badge_did_not_move(0, 0) is False     # 元々0なら騒がない


def test_does_not_flag_when_unknown():
    """読めない時は騒がない (誤検知で狼少年にしない)。"""
    assert CP.badge_did_not_move(None, 1) is False
    assert CP.badge_did_not_move(1, None) is False


def test_panel_checks_before_and_after_each_press():
    src = open(os.path.join(HQ, "control_panel.py"), encoding="utf-8").read()
    assert "self._badge_before = (_bk, badge_number(" in src, "押す前の件数を控えること"
    assert "self._check_badge_moved()" in src, "走行後に突き合わせること"
    i = src.index("def _check_badge_moved(")
    body = src[i:src.index(chr(10) + "    def ", i + 10)]
    assert "badge_did_not_move" in body and "_record_badge_drift" in body
    assert "押しても件数が減りませんでした" in body
