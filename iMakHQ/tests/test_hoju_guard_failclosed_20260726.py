# -*- coding: utf-8 -*-
"""補URL書込の URL共有ガードは fail-CLOSED であること (2026-07-26 監査指摘の修正)。

初版は「ガードを組めなければ警告して**書込を続行**」していた(fail-OPEN)。それだと
他出品が使用中の仕入元URLを掴み、両方売れた時に片方が履行不能 → キャンセル → Defect。
補URLは足せなくても出品は死なない(既存供給は残る)ので、判定不能なら書かないのが正。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import psa_hoju_fill as hf  # noqa: E402

NCOL = 40


def _row(url="", iid="", aux=()):
    r = [""] * NCOL
    r[hf.A], r[hf.B] = url, iid
    for k, u in enumerate(aux):
        r[hf.AUX0 + k] = u
    return r


def _vals(rows):
    return [[f"c{i}" for i in range(NCOL)]] + rows


def test_guard_not_ready_writes_nothing():
    """★ガードを組めなかったら 1行も書かない(fail-closed)。"""
    vals = _vals([_row(url="https://jp.mercari.com/item/m1", iid="111")])
    targets = [{"row": 2}]
    wb, added, dropped, _rep = hf.plan_aux_writeback(
        {0: ["https://jp.mercari.com/item/m9"]}, targets, vals, {}, guard_ok=False)
    assert wb == {} and added == 0 and dropped == []


def test_guard_ok_writes_free_urls():
    vals = _vals([_row(url="https://jp.mercari.com/item/m1", iid="111")])
    targets = [{"row": 2}]
    wb, added, dropped, _rep = hf.plan_aux_writeback(
        {0: ["https://jp.mercari.com/item/m9"]}, targets, vals, {}, guard_ok=True)
    assert added == 1 and dropped == []
    assert wb[2][0] == "https://jp.mercari.com/item/m9"


def test_guard_drops_url_owned_by_other_listing():
    """他出品(222)が使っているURLは書かない = 同一供給の二重掴みを防ぐ。"""
    vals = _vals([_row(url="https://jp.mercari.com/item/m1", iid="111")])
    targets = [{"row": 2}]
    owner = {"https://jp.mercari.com/item/m5": ["222"]}
    wb, added, dropped, _rep = hf.plan_aux_writeback(
        {0: ["https://jp.mercari.com/item/m5"]}, targets, vals, owner, guard_ok=True)
    assert wb == {} and added == 0
    assert dropped == [("https://jp.mercari.com/item/m5", ["222"])]


def test_existing_aux_are_preserved():
    """既存の補URLは消さない (値段が分からない = 押し出す根拠が無いので残る)。

    ★2026-09-05: 「既存は必ず残す」から「安い順に最大5本」に変えたが、
      値段の分からない既存を理由なく消すことはしない。
    """
    vals = _vals([_row(url="https://jp.mercari.com/item/m1", iid="111",
                       aux=("https://jp.mercari.com/item/mA",))])
    targets = [{"row": 2}]
    wb, added, _, _rep = hf.plan_aux_writeback(
        {0: ["https://jp.mercari.com/item/mB"]}, targets, vals, {}, guard_ok=True)
    assert wb[2][:2] == ["https://jp.mercari.com/item/mA", "https://jp.mercari.com/item/mB"]
    assert added == 1
