# -*- coding: utf-8 -*-
"""棚①と棚②を別の枠に置く (2026-09-03)。

## なぜ
棚は1つのボタンで ①(買えない) と ②(在庫はあるが売れない) を混ぜて落としていた。
②は **売れるかもしれない物を捨てる**判断で、①とは重さが全く違う。
同じ枠に並べると、取り返しのつかない End を軽い気持ちで押すことになる。

置き場所も分ける:
  棚① … 在庫なしの整理 (取下げと同じ棚)
  棚② … 在庫ありの棚。「直す」とは別枠にする
"""
import os
import re

_HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = open(os.path.join(_HQ, "control_panel.py"), encoding="utf-8").read()


def _cmd_of(label_head):
    i = _SRC.index('"label": "%s' % label_head)
    seg = _SRC[i:i + 700]
    m = re.search(r'"cmd":\s*\[([^\]]*)\]', seg)
    return " ".join(re.findall(r'"([^"]+)"', m.group(1)))


def test_two_separate_shelf_buttons_exist():
    assert '"label": "📉 棚① ' in _SRC
    assert '"label": "📉 棚② ' in _SRC


def test_each_button_runs_only_its_own_tier():
    assert "--tier 1" in _cmd_of("📉 棚① ")
    assert "--tier 2" in _cmd_of("📉 棚② ")


def test_tier2_comes_first_in_the_panel():
    """残枠が少ない今は②の方が空く額が大きい (実測 $244,785 / $111,599)。"""
    assert _SRC.index('"label": "📉 棚② ') < _SRC.index('"label": "📉 棚① ')


def test_tier2_has_its_own_group():
    """②は「直す」と同じ枠に置かない。"""
    assert '"evict2"' in _SRC
    assert "在庫あり — 落として枠を空ける" in _SRC
