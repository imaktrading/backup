# -*- coding: utf-8 -*-
"""LOW N列(仕入値SSOT)関数破損ガードの回帰テスト (2026-07-22)。

背景: 2026-07-22 のポイント込み実質仕入値 設計で N列は
=ARRAYFORMULA((M=現在価格 or F)−K=ポイント) のシート関数になった。
どこかのプロセスが N セルに値を書くと関数が静かに壊れ、陳腐化した仕入値で
誤った価格の出品が続く(fail-OPEN)。gshock_to_csv は取込前に N1 の式存在を確認し、
壊れていたら abort する(出品の正確性 > 継続)。
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "iMakG-shock")))
from gshock_to_csv import _assert_n_formula_intact  # noqa: E402


class _FakeCell:
    def __init__(self, value):
        self.value = value


class _FakeWs:
    def __init__(self, n1_value):
        self._n1 = n1_value

    def acell(self, label, value_render_option=None):
        assert label == "N1"
        assert value_render_option == "FORMULA", "式の存在確認は FORMULA render 必須"
        return _FakeCell(self._n1)


def test_intact_formula_passes():
    _assert_n_formula_intact(_FakeWs('=ARRAYFORMULA(IF(ROW(A:A)=1,"仕入れ価格（円）",...))'))


def test_value_overwritten_raises():
    """★本命: N1 が値に置き換わっていたら RuntimeError で出品を止める。"""
    with pytest.raises(RuntimeError):
        _assert_n_formula_intact(_FakeWs("仕入れ価格（円）"))


def test_empty_cell_raises():
    with pytest.raises(RuntimeError):
        _assert_n_formula_intact(_FakeWs(None))


def test_non_array_formula_raises():
    """単セル式(=F2-K2 等)への劣化も検知(全行カバーが保証されないため)。"""
    with pytest.raises(RuntimeError):
        _assert_n_formula_intact(_FakeWs("=F2-K2"))
