"""PSA目視HTML: 現物・回答・候補が重ならず、全部見えていること (2026-07-28).

経緯: 候補が多いと比較元が流れて見えなくなる → sticky で貼り付け → 今度は
「カードの上を通るから見にくい」(ユーザー指摘)。**貼り付けをやめて候補側を内側スクロール**に
変更した(補URL確証UIと同じ作り)。カード内で候補だけが動くので何も重ならない。

比較元が見えないまま候補を選ぶ = 同定の目視が成立しない(誤同定→誤出品の入口)。
"""
import os
import re

TOOL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "tools", "post_psa_review.py")


def _css(selector):
    src = open(TOOL, encoding="utf-8").read()
    m = re.search(re.escape(selector) + r"\{([^}]*)\}", src)
    assert m, f"CSS が無い: {selector}"
    return m.group(1)


def test_candidates_scroll_inside_the_card():
    """候補は自分の枠内でスクロールする(ページごと流れると現物が見えなくなる)。"""
    c = _css(".candidates")
    assert "overflow-y:auto" in c
    assert re.search(r"max-height:\d+vh", c)


def test_nothing_is_pinned_over_the_card():
    """sticky で貼り付けるとカードの上に重なって見にくい(ユーザー指摘)。"""
    for sel in (".confirm", ".answer-btns"):
        assert "position:sticky" not in _css(sel), sel


def test_reference_does_not_eat_the_screen():
    """現物が画面を占有すると候補が見えない。高さ上限を持つこと。"""
    assert re.search(r"max-height:\d+vh", _css(".confirm"))


def test_card_fits_roughly_one_screen():
    """現物 + 候補 が画面に収まる範囲(合計 <= 100vh)であること。"""
    ref = int(re.search(r"max-height:(\d+)vh", _css(".confirm")).group(1))
    cand = int(re.search(r"max-height:(\d+)vh", _css(".candidates")).group(1))
    assert ref + cand <= 100


def test_answer_buttons_have_background():
    """候補が透けて読めなくならないように背景を持つ。"""
    assert "background" in _css(".answer-btns")
