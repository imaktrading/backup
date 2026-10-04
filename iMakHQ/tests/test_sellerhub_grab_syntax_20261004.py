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


def test_collect_takes_traffic_report():
    """夜のバッチがトラフィックレポートも置き場へ移す (2026-10-04 棚② の「埋もれた」判定用)。"""
    import sys
    sys.path.insert(0, os.path.join(HERE, ".."))
    import seller_hub_collect as C
    names = [n for n in dir(C) if callable(getattr(C, n))]
    fn = next(getattr(C, n) for n in names if n.startswith("_is") or n.startswith("is_"))
    assert fn("eBay-ListingsTrafficReport-Oct-04-2026-03_53_31-0700-13332226331.csv")


def test_extension_grabs_traffic_after_lqr():
    src = open(os.path.join(HERE, "content.js"), encoding="utf-8").read()
    assert 'sessionStorage.setItem(STAGE, "traffic")' in src and "function grabTraffic" in src
