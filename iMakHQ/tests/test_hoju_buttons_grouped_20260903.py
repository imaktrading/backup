# -*- coding: utf-8 -*-
"""補URLのボタンを系統ごとに並べる (2026-09-03)。

## なぜ
補URLのボタンが「🆕 補URL 当日分 / 🔎 slice2 / 🩹 slice3」という名前で、
**どれが PSA でどれが一番くじか分からなかった**。UT を足すと3系統が混ざる。
ユーザー要望「PSAなのか一番くじなのかTシャツなのかグルーピングして分かりやすく」。

系統名をラベルに入れ、パネルでは系統ごとの小枠に分ける。
"""
import os
import re

_HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = open(os.path.join(_HQ, "control_panel.py"), encoding="utf-8").read()


def _labels():
    return re.findall(r'"label": "([^"]*補URL[^"]*)"', _SRC)


def test_every_aux_button_says_which_product_line():
    """系統名 (PSA / UT / 一番くじ / 全系統) が入っていること。"""
    for lab in _labels():
        assert any(k in lab for k in ("PSA", "UT", "一番くじ", "全系統")), lab


def test_ut_has_both_search_and_confirm():
    assert '"label": "🔎 UT 補URL 夜間検索"' in _SRC
    assert '"label": "🩹 UT 補URL 昼の目視"' in _SRC


def test_ut_search_does_not_write_to_the_sheet():
    """検索は貯めるだけ。書くのは目視の後 (補URLの決まり)。"""
    i = _SRC.index('"label": "🔎 UT 補URL 夜間検索"')
    seg = _SRC[i:i + 700]
    assert '"ut_hoju_fill.py", "search"' in seg


def test_panel_splits_the_three_product_lines():
    """商材ごとに箱を作っている (PSA / UT / 一番くじ)。"""
    i = _SRC.index('for _name in (')
    assert '"PSA (TCG)", "Tシャツ (UT)", "一番くじ"' in _SRC[i:i + 120]
    # どのボタンがどの商材かを判定している
    assert "def _line_of(" in _SRC


def test_panel_boxes_are_per_product_line_in_work_order():
    """★2026-09-03 ユーザー要望「商材ごとに作業順に並べて、囲って」。

    従来は 工程ごと (発見 / 出品前チェック / 補URL) の箱で、1つの箱に PSA と
    一番くじと UT が混ざり、自分の商材の次の一手が読み取れなかった。
    """
    assert "📦 {_name} — 出品 → 出品前チェック → 補URL" in _SRC
    # 作業順 (当日分 → 夜間検索 → 昼の目視) で並べている
    i = _SRC.index("_STEP = [")
    assert '"当日分", "夜間検索", "昼の目視"' in _SRC[i:i + 120]
    # 箱に出す商材は、上のカテゴリ一覧では二重に出さない
    assert '_BOXED = {"PSA TCG", "Tシャツ", "一番くじ"}' in _SRC


def test_ut_buttons_show_counts():
    """ヒントに件数を出し、押す価値がある時だけ青にする。"""
    assert '"badge": "ut_search"' in _SRC
    assert '"badge": "ut_confirm"' in _SRC
    assert '"ut_search": ut_s_txt' in _SRC
    assert '"ut_search": bool(_ut.get("search"))' in _SRC
    assert '"ut_confirm": bool(_ut.get("confirm"))' in _SRC


def test_every_ut_button_has_a_hint():
    for lab in ('🔎 UT 補URL 夜間検索', '🩹 UT 補URL 昼の目視'):
        i = _SRC.index('"label": "%s"' % lab)
        assert '"tip"' in _SRC[i:i + 800], lab
