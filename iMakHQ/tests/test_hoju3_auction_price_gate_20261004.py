# -*- coding: utf-8 -*-
"""補URL③ の目視に AUC (オークション) と「今の仕入値より高い候補」が出ていた (2026-10-04・AUC は4回目)。

- 入口: 補URL の夜探しの API 検索 (_ApiSource.search) がオークションを落としていなかった
- 目視待ちから混ぜる候補には値段の門が無かった
- 家で動いた時に確認画面が2つ開いていた (確認画面の処理 + 神風の中継)
"""
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
import mercari_psa_resource as mp  # noqa: E402
import psa_hoju_fill as H  # noqa: E402
import cache_buyable_sweep as CS  # noqa: E402

NS = types.SimpleNamespace


def test_api_search_drops_auction():
    assert mp.is_api_auction(NS(auction=NS(id_="a1")))
    assert not mp.is_api_auction(NS(auction=None))
    assert not mp.is_api_auction(NS())

    src = mp._ApiSource.__new__(mp._ApiSource)
    src.fallen = False
    src.kind = {}
    src._R = NS(SortBy=NS(SORT_PRICE=1), SortOrder=NS(ORDER_ASC=1), Status=NS(STATUS_ON_SALE=1))
    items = [NS(id_="m1", price=5000, name="PSA10 ミュウ", item_type="ITEM_TYPE_MERCARI", auction=None),
             NS(id_="m2", price=3000, name="PSA10 ミュウ", item_type="ITEM_TYPE_MERCARI", auction=NS(id_="x"))]
    src.api = NS(search=lambda *a, **k: None)
    src._run = lambda coro: NS(items=items)
    import time as _t
    orig = _t.sleep
    _t.sleep = lambda *_: None
    try:
        out = src.search("PSA10 ミュウ")
    finally:
        _t.sleep = orig
    assert [o["href"].rsplit("/", 1)[-1] for o in out] == ["m1"]


def test_cost_filter_uses_candidate_price_when_table_lacks(monkeypatch):
    """目視待ちの候補は値段表に無いことがある → 候補が持つ値段 (棚卸しが書いた今の値段) で門を掛ける。"""
    monkeypatch.setattr(H, "_row_cost_and_dead", lambda t, vals: (8000, False))
    monkeypatch.setattr(H, "min_gain_for", lambda t: 0)
    monkeypatch.setattr(H, "_price_cache_get", lambda hd: {})
    keep, drop = H.filter_candidates_by_cost(
        [{"url": "https://jp.mercari.com/item/m1", "price": 15000},
         {"url": "https://jp.mercari.com/item/m2", "price": 7000}], {"row": 2}, [])
    assert [c["url"][-2:] for c in keep] == ["m2"] and [c["url"][-2:] for c in drop] == ["m1"]


def test_pending_merge_goes_through_cost_gate():
    src = open(os.path.join(HERE, "..", "tools", "psa_hoju_fill.py"), encoding="utf-8").read()
    i = src.index("_pend = _pending_by_iid.get(iid)")
    assert "filter_candidates_by_cost(" in src[i:i + 2500]
    assert "load_not_buyable" in src[i:i + 2500]


def test_cache_item_urls_only_individual_items():
    cache = {"1": {"mercari": {"best": [5000, "https://jp.mercari.com/item/m1", "a"],
                               "all_cands": [[6000, "https://jp.mercari.com/shops/product/S1", "b"]],
                               "loose_cands": [[7000, "https://jp.mercari.com/item/m2", "c"]]}},
             "2": {"mercari": None}}
    assert CS.cache_item_urls(cache) == {"https://jp.mercari.com/item/m1", "https://jp.mercari.com/item/m2"}


def test_console_does_not_relay_open_when_run_falls_back_home():
    src = open(os.path.join(HERE, "..", "console", "server.py"), encoding="utf-8").read()
    assert '"家で動かします" in line' in src and "if _rcmd and not _at_home:" in src


def test_drop_unbuyable_now_before_screen():
    """画面に出す直前にメルカリ個人出品を確かめ、買えない物は出さずに台帳へ (2026-10-04「まだAUCでてる」)。"""
    cands = [{"url": "https://jp.mercari.com/item/m1"}, {"url": "https://jp.mercari.com/item/m2"},
             {"url": "https://snkrdunk.com/apparels/1/used/2"}, {"url": "https://jp.mercari.com/item/m3"}]
    remembered = []
    out = H.drop_unbuyable_now(
        cands, check=lambda urls: ({urls[0]: True, urls[1]: False}, {}, [urls[2]]),
        remember=lambda u, why: remembered.append(u))
    assert [c["url"][-2:] for c in out] == ["m1", "/2", "m3"]
    assert remembered == ["https://jp.mercari.com/item/m2"]


def test_drop_unbuyable_now_keeps_all_when_check_fails():
    cands = [{"url": "https://jp.mercari.com/item/m1"}]

    def boom(urls):
        raise RuntimeError("x")
    assert H.drop_unbuyable_now(cands, check=boom, remember=lambda u, w: None) == cands


def test_screen_calls_drop_unbuyable_now():
    src = open(os.path.join(HERE, "..", "tools", "psa_hoju_fill.py"), encoding="utf-8").read()
    assert "cands = drop_unbuyable_now(cands)" in src
