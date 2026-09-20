# -*- coding: utf-8 -*-
"""確認したのに1本も入らなかった行を記録する (2026-09-20)。

ユーザー「押しても残数が変わってない」(補URL③ 入れ替え: 3件 → 3件)。
入れ替えは「既存より安い候補だけが枠に入る」ので、既に安いものが5本ある行では
人が確認しても全部はじかれる。その結果がどこにも残らず、**次回また同じ候補を見せて
また件数が減らない**状態だった。

実測 2026-09-20 20:44: 820000791250 / 358837874577 / 358712961302 の3行が該当。
候補 (snkrdunk ¥33,700 等) は既存5本より高く、枠に入れなかった。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(r"C:\dev\iMak\iMakHQ", "tools"))

import psa_hoju_fill as H  # noqa: E402

_U_IN = "https://snkrdunk.com/apparels/730964/used/50305214"
_U_OUT = "https://snkrdunk.com/apparels/730964/used/50325133"


def _vals(row_urls):
    """AUX0 以降に補URL が並ぶ 1行だけのシート。"""
    r = [""] * (H.AUX0 + H.AUXN)
    for k, u in enumerate(row_urls):
        r[H.AUX0 + k] = u
    return [r]


def test_全部はじかれた行を拾う():
    tgt = [{"itemID": "820000791250", "row": 1, "title": "x"}]
    got = H.confirmed_but_nothing_written({0: [_U_OUT]}, tgt, _vals([_U_IN]), {})
    assert got == [(0, [_U_OUT])], got


def test_入った行は拾わない():
    tgt = [{"itemID": "820000791250", "row": 1, "title": "x"}]
    got = H.confirmed_but_nothing_written({0: [_U_IN]}, tgt, _vals([_U_IN]), {})
    assert got == []


def test_一部でも入ったら拾わない():
    """1本でも役に立ったなら、その行は仕事が進んでいる。"""
    tgt = [{"itemID": "820000791250", "row": 1, "title": "x"}]
    got = H.confirmed_but_nothing_written({0: [_U_IN, _U_OUT]}, tgt, _vals([_U_IN]), {})
    assert got == []


def test_書込計画がある時はそちらを見る():
    """このあと書かれる内容で判定する (書く前のシートで判定しない)。"""
    tgt = [{"itemID": "820000791250", "row": 1, "title": "x"}]
    got = H.confirmed_but_nothing_written({0: [_U_OUT]}, tgt, _vals([_U_IN]),
                                          {1: [_U_OUT, _U_IN]})
    assert got == []
