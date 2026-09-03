# -*- coding: utf-8 -*-
"""棚が「これから戻す出品」を落とさない (2026-09-03)。

## 実害
棚の ①(数量0) は **需要を見ない**。一方 PSA再仕入れは「数量0 で需要があった」出品を拾い、
仕入元を見つけて数量を戻す。つまり **同じ数量0を取り合っていた**。
実測 2026-09-03: 再仕入れが戻す予定の12件のうち **8件** が①の対象に入っていた。
棚のボタンを押した日に、目視で確認して仕入元まで押さえた出品が消える。

取下げ(CULL) は「生涯ずっと表示もクリックも販売もゼロ」に限るので、元々重ならない。
重なっていたのは棚①だけ。

## fail-closed
再仕入れの予定が読めない時は **空集合** = 従来どおり選ぶ。棚を止めない。
"""
import os
import sys

_HQ_TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
if _HQ_TOOLS not in sys.path:
    sys.path.insert(0, _HQ_TOOLS)

import shelf_evict as SE  # noqa: E402


def _oos(iid):
    return {"item_id": iid, "qty": 0, "sold_qty": 0, "sales90": 0, "age_days": 200}


def test_restock_pending_listing_is_not_dropped():
    """戻す予定の出品は、数量0でも落とさない。"""
    assert SE.tier_of(_oos("keep"), restock_pending={"keep"}) is None
    assert SE.tier_of(_oos("other"), restock_pending={"keep"}) == SE.TIER_OOS


def test_no_pending_list_behaves_as_before():
    """読めなかった時 (空集合/None) は従来どおり落とす = 棚を止めない。"""
    assert SE.tier_of(_oos("x"), restock_pending=set()) == SE.TIER_OOS
    assert SE.tier_of(_oos("x")) == SE.TIER_OOS


def test_guard_also_protects_in_stock_stale():
    """在庫ありの期限超え (②) でも、戻す予定なら触らない。"""
    row = {"item_id": "keep", "qty": 1, "sold_qty": 0, "sales90": 0, "age_days": 400}
    assert SE.tier_of(row, category="TCG") == SE.TIER_STALE
    assert SE.tier_of(row, category="TCG", restock_pending={"keep"}) is None


def test_pick_passes_the_guard_through():
    rows = [_oos("keep"), _oos("drop")]
    picked, _ = SE.pick(rows, target=10**9, shelf_of=lambda r: 100.0,
                        restock_pending={"keep"})
    assert [r["item_id"] for _t, r in picked] == ["drop"]
