"""PSA目視HTML: 候補が多くても比較元(現物)が見えていること (2026-07-28).

ユーザー報告「候補が多いと、比較元がスクロールされて分からなくなる」。
比較元が見えない状態で候補を選ぶ = 同定の目視が成立しない(誤同定→誤出品の入口)。
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


def test_reference_block_is_sticky():
    c = _css(".confirm")
    assert "position:sticky" in c
    assert re.search(r"top:\d+px", c)


def test_sticky_offset_clears_the_toolbar():
    """ツールバー(sticky top:0)の下に出ないと隠れる。"""
    assert "position:sticky;top:0" in _css(".toolbar")
    top = int(re.search(r"top:(\d+)px", _css(".confirm")).group(1))
    assert top >= 40


def test_reference_stays_below_toolbar_in_stacking():
    """z-index はツールバーより低く、候補カードより高い。"""
    tb = int(re.search(r"z-index:(\d+)", _css(".toolbar")).group(1))
    cf = int(re.search(r"z-index:(\d+)", _css(".confirm")).group(1))
    assert cf < tb


def test_reference_does_not_eat_the_screen():
    """画面を占有すると候補が見えない。高さ上限を持つこと。"""
    c = _css(".confirm")
    assert "max-height" in c


def test_answer_buttons_are_reachable_while_scrolling():
    """候補をスクロールしても 合ってる/違う/該当なし に手が届くこと。
    現物(上 sticky)と重ならないよう、回答は **画面下** に固定する
    (現物ブロックの高さは可変なので、上に2つ並べると重なる)。"""
    c = _css(".answer-btns")
    assert "position:sticky" in c
    assert "bottom:0" in c
    assert "background" in c        # 透過だと候補が透けて読めない


def test_parent_has_no_overflow_that_breaks_sticky():
    """親に overflow:hidden/auto が付くと sticky が効かなくなる。"""
    assert "overflow" not in _css(".target")
