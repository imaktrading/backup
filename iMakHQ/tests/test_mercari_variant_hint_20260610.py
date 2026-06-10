# -*- coding: utf-8 -*-
"""Step6 P3: メルカリ pick_cheapest_psa10 が canonical変種 hint で正変種を選ぶ + fail-closed."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import mercari_psa_resource as mp


def _it(price, name):
    return {"price": price, "name": name, "href": f"https://jp.mercari.com/item/m{price}"}


# 同番号 OP11-106 に 神速(安) と EGGHEAD(高) の2変種が出品 (価格昇順)
ITEMS = [
    _it(45000, "PSA10 ゼウス OP11-106 神速の拳"),
    _it(160000, "PSA10 ゼウス OP11-106 EGGHEAD CRISIS"),
]
HINT_SHINSOKU = ["ブースターパック 神速の拳【OP-11】", "alt_art", "R", "ゼウス"]
HINT_EGGHEAD = ["エクストラブースター EGGHEAD CRISIS【EB-04】", "alt_art", "SPカード", "ゼウス"]


def test_hint_picks_right_variant_not_just_cheapest():
    """EGGHEAD変種が欲しい時、安い神速(¥45k)でなく EGGHEAD(¥160k)を選ぶ。"""
    got = mp.pick_cheapest_psa10(ITEMS, "OP11-106", variant_hint=HINT_EGGHEAD)
    assert got is not None and got[0] == 160000


def test_hint_picks_cheap_variant_when_that_is_target():
    got = mp.pick_cheapest_psa10(ITEMS, "OP11-106", variant_hint=HINT_SHINSOKU)
    assert got is not None and got[0] == 45000


def test_no_hint_falls_back_to_cheapest():
    """hint無(KEY未解決)は従来どおり番号一致の最安。"""
    got = mp.pick_cheapest_psa10(ITEMS, "OP11-106")
    assert got is not None and got[0] == 45000


def test_multi_variant_hint_no_match_failclosed():
    """複数候補・hintがどれにも当たらない → 誤variant回避で None。"""
    got = mp.pick_cheapest_psa10(ITEMS, "OP11-106", variant_hint=["全然違うセットXYZ"])
    assert got is None


def test_single_match_with_unmatched_hint_still_returns():
    """候補単一なら hint未一致でも採用(seller がset未記載なだけ=変種曖昧なし)。"""
    items = [_it(45000, "PSA10 ゼウス OP11-106")]
    got = mp.pick_cheapest_psa10(items, "OP11-106", variant_hint=HINT_EGGHEAD)
    assert got is not None and got[0] == 45000


def test_no_number_match_none():
    items = [_it(1000, "PSA10 ルフィ OP01-001")]
    assert mp.pick_cheapest_psa10(items, "OP11-106", variant_hint=HINT_SHINSOKU) is None
