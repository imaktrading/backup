# -*- coding: utf-8 -*-
"""補URL③ 補充のついでに入れ替えも同じ目視で片づける (2026-09-29 ユーザー確定)。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import psa_hoju_fill as H  # noqa: E402


def _t(n):
    return [{"itemID": str(i), "n_backups": nb} for i, nb in enumerate(n)]


def test_fill_and_swap_are_cut_separately():
    tg = _t([0, 1, 2, 3, 4, 5, 4])                # 補充4件 + 入れ替え3件
    items = [{"i": k} for k in range(len(tg))]
    it, t = H.split_fill_and_swap(items, tg, limit=2, swap_limit=2)
    assert [x["n_backups"] for x in t] == [0, 1, 4, 5]   # 補充が多い日も入れ替えが出る
    assert [x["i"] for x in it] == [0, 1, 4, 5]


def test_without_swap_limit_keeps_old_behavior():
    tg = _t([4, 5, 4])                            # 入れ替えボタン単独 (swap_limit なし)
    items = [{"i": k} for k in range(3)]
    it, t = H.split_fill_and_swap(items, tg, limit=2)
    assert [x["i"] for x in it] == [0, 1]


def test_fill_button_asks_for_swap_too():
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import control_panel as cp
    fill = [s for s in cp.SCRIPTS if s.get("label", "").endswith("補充") and "psa_hoju_fill.py" in s.get("cmd", [])]
    assert fill and "--swap-limit=15" in fill[0]["cmd"]
