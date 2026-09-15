# -*- coding: utf-8 -*-
"""売れた分の補充: 未発送の注文があっても、ほかに買える仕入元が残るなら戻す (2026-09-15)。

ユーザー「どれかで仕入れたら、仕入元は売り切れになる。それ以外の仕入元が活きているなら、戻してもいいのでは？」
実例: 358887214446 カビゴン = 仕入元1 + 補URL5 (どれも買えない記録に無い) なのに、未発送の注文で止めていた。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import sheet_io as S  # noqa: E402
import sold_restock as R  # noqa: E402

MAIN = "https://jp.mercari.com/item/m18020813322"
AUX1 = "https://snkrdunk.com/apparels/393022/used/49839372"


def _row(main="", aux=()):
    r = [""] * 40
    r[0] = main
    for k, u in enumerate(aux):
        r[S.PRODUCT_COL_AUX_START + k] = u
    return r


def test_two_live_supplies_allow_restock():
    assert R.has_spare_supply(_row(MAIN, [AUX1]), {})


def test_single_supply_waits():
    assert not R.has_spare_supply(_row(MAIN), {})
    assert not R.has_spare_supply(_row("", [AUX1]), {})


def test_dead_urls_are_not_counted():
    assert not R.has_spare_supply(_row(MAIN, [AUX1]), {AUX1: {"why": "売り切れ"}})
    assert not R.has_spare_supply(_row(MAIN, [AUX1 + "?x=1"]), {AUX1: {"why": "売り切れ"}})


def test_same_url_twice_counts_once():
    assert not R.has_spare_supply(_row(MAIN, [MAIN]), {})


def test_unreadable_ledger_waits():
    assert not R.has_spare_supply(_row(MAIN, [AUX1]), None)


def test_both_hold_points_use_the_rule():
    src = open(R.__file__, encoding="utf-8").read()
    assert src.count("in pending and not has_spare_supply(row, _nb)") == 2
