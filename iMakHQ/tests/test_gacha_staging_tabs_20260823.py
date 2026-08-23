# -*- coding: utf-8 -*-
"""ガチャの中間スプシは **店ごとにタブが分かれている** (2026-08-23)。

## 何が起きていたか
出品側 (`gacha_to_csv.py`) は `rakuten_gacha` という1本のタブを決め打ちしていた。
ところが抽出くんは店ごとに分けて書いており、その名前のタブは **実在しない**。
`read_sheet` が StopIteration で落ち、**ガチャの出品CSVが1件も作れない状態**が続いていた
(抽出くんからの報告 2026-08-22 / 残務№147)。

実機のタブ:
    rakuten_auc_toysanta 141 / rakuten_auc_yuyou 107 / rakuten_mirakikaku 35 /
    rakuten_mejirushi 16 / rakuten_jugem2020 3  = 302行

## 直し方
タブ名を並べて持つと、店が増えるたびに抽出くんと出品くんの両方で書き写すことになる
(= 必ずいつかズレる)。**前方一致 `rakuten_` で拾う**ようにした。店が増えても何もしなくてよい。

行番号は **タブごと**に振られているので、どの行がどのタブのものかを持ち回る。
持たないと、公式URL (I列) の書き戻しが **別の店の行を潰す**。
"""
import os
import sys

import pytest

_TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "iMakHQ", "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import gacha_to_csv as G  # noqa: E402

_REAL = ["シート1", "psa10", "rakuten_auc_yuyou", "rakuten_auc_toysanta",
         "rakuten_mirakikaku", "rakuten_jugem2020", "rakuten_mejirushi"]


def test_all_store_tabs_are_picked():
    assert G.pick_tabs(_REAL) == [
        "rakuten_auc_toysanta", "rakuten_auc_yuyou", "rakuten_jugem2020",
        "rakuten_mejirushi", "rakuten_mirakikaku"]


def test_unrelated_tabs_are_not_picked():
    got = G.pick_tabs(_REAL)
    assert "psa10" not in got and "シート1" not in got


def test_new_store_needs_no_code_change():
    """店が増えても書き写さなくてよい (これが前方一致にした理由)。"""
    assert "rakuten_newshop" in G.pick_tabs(_REAL + ["rakuten_newshop"])


def test_explicit_tab_narrows_to_one():
    assert G.pick_tabs(_REAL, "rakuten_mirakikaku") == ["rakuten_mirakikaku"]


def test_missing_tab_returns_empty_not_crash():
    """昔の決め打ち名を渡しても、落ちずに空を返す (呼び側が理由付きで止める)。"""
    assert G.pick_tabs(_REAL, "rakuten_gacha") == []


def test_order_is_stable():
    """順番が走行ごとに変わると I列の書き戻し先が動く。"""
    assert G.pick_tabs(_REAL) == G.pick_tabs(list(reversed(_REAL)))


@pytest.mark.parametrize("bad", ["rakuten_gacha", "gacha", "rakuten"])
def test_old_hardcoded_tab_is_gone(bad):
    src = open(os.path.join(_TOOLS, "gacha_to_csv.py"), encoding="utf-8").read()
    assert f'STAGING_TAB = "{bad}"' not in src


def test_rows_carry_their_tab():
    """行に出所のタブが付いていること (書き戻しが別の店を潰さないため)。"""
    src = open(os.path.join(_TOOLS, "gacha_to_csv.py"), encoding="utf-8").read()
    assert '"tab": w.title' in src, "読んだ行にタブ名を付けていない"
    assert 'it["tab"] = tab' in src, "出品対象にタブ名を引き継いでいない"
    assert "by_tab.setdefault" in src, "書き戻しをタブごとに分けていない"
