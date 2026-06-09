#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""listing_funnel: OOS の RESTOCK/CULL 判定を露出(impr_total)ベースにする回帰テスト (2026-06-09)。

バグ: RESTOCK/CULL の判定が sold+watch+sales90 だけ。OOS品は買えない=販売もクリックも
抑制されるので「売れてない/クリック0」は不人気の証拠にならない。これを死筋扱いすると
「eBayが大量に表示してる(関連性あり)がOOSで買えなかった」良品が CULL に誤分類される
(実測: CULL 1755中 474件が impr_total>=10。Luffy/Ace/Uta/Boa 等の人気どころ)。
修正: impr_total>=10(eBayが十分表示=関連性) を需要シグナルとして RESTOCK。露出もほぼ無い
(impr_total<10)かつ販売/watch/90d=0 だけが真の死筋=CULL。
"""
import importlib.util
import os

_FUNNEL = os.path.join(os.path.dirname(__file__), "..", "tools", "listing_funnel.py")
_spec = importlib.util.spec_from_file_location("listing_funnel", _FUNNEL)
lf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lf)


def _oos(iid, **kw):
    r = {"item_id": iid, "qty": 0, "sold_qty": 0, "watch": 0, "sales90": 0, "age_days": 60,
         "price": 100.0, "trend_price": 0.0, "impr": 0.0, "ctr": 0.0,
         "impr_total": 0.0, "ctr_total": 0.0, "has_lqr": False, "has_pl": False}
    r.update(kw)
    return r


def _flags(c, iid):
    return {k for k, v in c.items() if isinstance(v, list) and any(r.get("item_id") == iid for r in v)}


def test_oos_with_exposure_is_restock_even_zero_clicks():
    """OOS・実売0・クリック0 でも eBay が1000表示(関連性あり) → RESTOCK。CULLにしない。"""
    c = lf.classify([_oos("exposed", impr_total=1000, ctr_total=0.0)])
    f = _flags(c, "exposed")
    assert "RESTOCK" in f
    assert "CULL" not in f


def test_oos_no_exposure_no_demand_is_cull():
    """OOS・eBayがほぼ表示しない(impr_total=0)・販売/watch0 → 真の死筋=CULL。"""
    c = lf.classify([_oos("dead")])
    f = _flags(c, "dead")
    assert "CULL" in f
    assert "RESTOCK" not in f


def test_oos_any_exposure_is_restock():
    """OOS・impr_total=1 でも eBayが表示した(関連性あり) → RESTOCK。CULL は impr完全0だけ。"""
    c = lf.classify([_oos("tiny", impr_total=1, ctr_total=0.0)])
    f = _flags(c, "tiny")
    assert "RESTOCK" in f
    assert "CULL" not in f


def test_oos_with_watch_still_restock():
    """従来通り: watch>0 の OOS は RESTOCK (後方互換)。"""
    c = lf.classify([_oos("watched", watch=3)])
    f = _flags(c, "watched")
    assert "RESTOCK" in f
    assert "CULL" not in f
