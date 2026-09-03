# -*- coding: utf-8 -*-
"""棚のボタンは②だけ。①は取下げに任せる (2026-09-03 ユーザー確定)。

## なぜ
棚は1つのボタンで ①(買えない) と ②(在庫はあるが売れない) を混ぜて落としていた。
②は **売れるかもしれない物を捨てる**判断で、①とは重さが全く違う。
同じボタンだと、取り返しのつかない End を軽い気持ちで押すことになる。

分けたうえで比べたら、**①は取下げと落とす相手が同じ**だった (どちらも
数量0・生涯需要ゼロ)。違うのは止まり方だけ (取下げ=200件/回 / 棚①=金額)。
2つ要らないので **棚①は置かない**。数量0の整理は取下げ1本にする。
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


def test_only_tier2_has_a_button():
    """棚①は置かない。数量0の整理は取下げ1本 (落とす相手が同じため)。"""
    assert '"label": "📉 棚② ' in _SRC
    assert '"label": "📉 棚① ' not in _SRC


def test_the_shelf_button_never_touches_tier1():
    """②のボタンが①まで落とさないこと (混ぜると重い方を軽く押す)。"""
    assert "--tier 2" in _cmd_of("📉 棚② ")


def test_cull_button_still_exists():
    """数量0の整理はこちらが担当する。"""
    assert '"label": "🗑 取下げ' in _SRC


def test_tier2_has_its_own_group():
    """②は「直す」と同じ枠に置かない。"""
    assert '"evict2"' in _SRC
    assert "在庫あり — 落として枠を空ける" in _SRC
