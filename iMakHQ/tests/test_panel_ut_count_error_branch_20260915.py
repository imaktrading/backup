# -*- coding: utf-8 -*-
"""UT の残件が取れない時も、パネルの残件表示全体を落とさない (2026-09-15)。

実害: PSA 補URL ③ を押した後「⚠️ 補URL 残件の取得に失敗: UnboundLocalError」→
「押しても件数が減りませんでした (35件 → 35件)」。UT 側がエラーを返した分岐で
ut_sn_txt / ut_sw_txt を入れておらず、by_kind を組む所で落ちて全ボタンが前回値になっていた。
"""
import os
import re

HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_error_branch_assigns_every_ut_text_used_later():
    src = open(os.path.join(HQ, "control_panel.py"), encoding="utf-8").read()
    i = src.index('if _ut.get("error"):')
    err_branch = src[i:src.index("else:", i)]
    assigned_err = set(re.findall(r"\b(ut_\w+_txt)\b", err_branch))
    j = src.index("by_kind = {", i)
    used = set(re.findall(r"\b(ut_\w+_txt)\b", src[j:src.index("}", j)])) - {"ui_txt"}
    assert used <= assigned_err, sorted(used - assigned_err)
