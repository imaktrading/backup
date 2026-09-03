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
    assert '"PSA (TCG)": []' in _SRC or '_buckets = {"PSA (TCG)"' in _SRC
    assert "UT (Tシャツ)" in _SRC
    assert "一番くじ" in _SRC
