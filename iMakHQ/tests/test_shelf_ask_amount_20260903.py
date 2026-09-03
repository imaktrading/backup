# -*- coding: utf-8 -*-
"""棚のボタンは「いくら空けるか」を聞いてから走る (2026-09-03)。

## なぜ
棚は「その日に出した金額」に届いたら止まる。だから **何度押しても2回目以降は
ほぼ何も落ちない** (目標がもう埋まっている)。たくさん空けたい日に、押す回数で
調整しようとしても効かない。

押す前に1回だけ額を聞く。空欄なら従来どおり「今日出した分と同じだけ」。
"""
import os
import re

_HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = open(os.path.join(_HQ, "control_panel.py"), encoding="utf-8").read()


def test_shelf_button_asks_for_the_amount():
    i = _SRC.index('"label": "📉 棚② ')
    assert '"ask_amount": True' in _SRC[i:i + 900]


def test_amount_is_passed_as_a_flag():
    """入れた額は --amount で渡す (shelf_evict の目標額)。"""
    assert 'cmd.extend(["--amount", _v])' in _SRC


def test_blank_keeps_the_old_behaviour():
    """空欄なら --amount を足さない = 今日出した分と同じだけ。"""
    i = _SRC.index('if script.get("ask_amount"):')
    seg = _SRC[i:i + 900]
    assert "if _v:" in seg, "空欄チェックが無い"


def test_cancel_does_not_run():
    """キャンセル (None) で走らせない。取り返しがつかない操作なので。"""
    i = _SRC.index('if script.get("ask_amount"):')
    seg = _SRC[i:i + 900]
    assert "if _v is None:" in seg and "return" in seg
