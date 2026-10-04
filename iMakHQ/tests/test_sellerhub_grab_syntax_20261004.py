# -*- coding: utf-8 -*-
"""拡張 sellerhub_grab の JS が文法として読めること (2026-10-04: 文字列の中に改行を入れてしまい、
拡張全体が動かなくなった = 毎日のレポート取りも止まった)。esprima が無ければ飛ばす。"""
import os

import pytest

HERE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools", "sellerhub_grab")


@pytest.mark.parametrize("name", ["content.js", "background.js"])
def test_extension_js_parses(name):
    esprima = pytest.importorskip("esprima")
    esprima.parseScript(open(os.path.join(HERE, name), encoding="utf-8").read())
