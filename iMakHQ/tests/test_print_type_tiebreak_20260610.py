# -*- coding: utf-8 -*-
"""Step6 P3 続: 同一set の 通常/パラレル/SP を print種別で tie-break (SNKRDUNK + メルカリ)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import snkrdunk_psa_resource as sp
import mercari_psa_resource as mp


def test_print_signal():
    assert sp._print_signal(["A Fist of Divine Speed", "alt_art", "R", "ゼウス"]) == "P"
    assert sp._print_signal(["Egghead Crisis", "alt_art", "SPカード", "ゼウス"]) == "SPC"
    assert sp._print_signal(["A Fist of Divine Speed", "", "R", "ゼウス"]) == ""   # 通常


def test_item_print():
    assert sp._item_print("Zeus R-P [OP11-106]") == "P"
    assert sp._item_print("Zeus R-SPC [OP11-106]") == "SPC"
    assert sp._item_print("Zeus R [OP11-106]") == ""           # 通常(suffix無)
    assert sp._item_print("ゼウス OP11-106 パラレル") == "P"


# 同一set "A Fist of Divine Speed" に 通常(R) と パラレル(R-P)、別setに SP
SNKR = {"tradingCards": [
    {"id": 520553, "productNumber": "", "name": 'Zeus R-P [OP11-106](Booster Pack "A Fist of Divine Speed")'},
    {"id": 531946, "productNumber": "", "name": 'Zeus R [OP11-106](Booster Pack "A Fist of Divine Speed")'},
    {"id": 751309, "productNumber": "", "name": 'Zeus R-SPC [OP11-106](Extra Booster "Egghead Crisis")'},
]}
H_P1 = ["A Fist of Divine Speed", "A Fist of Divine Speed", "alt_art", "R", "ゼウス"]   # parallel
H_BASE = ["A Fist of Divine Speed", "A Fist of Divine Speed", "", "R", "ゼウス"]         # 通常
H_P2 = ["Egghead Crisis", "Egghead Crisis", "alt_art", "SPカード", "ゼウス"]            # SP別set


def test_snkrdunk_same_set_parallel_picks_RP():
    assert sp.parse_search_for_card(SNKR, "OP11-106", variant_hint=H_P1) == 520553


def test_snkrdunk_same_set_normal_picks_R():
    assert sp.parse_search_for_card(SNKR, "OP11-106", variant_hint=H_BASE) == 531946


def test_snkrdunk_cross_set_sp_picks_egghead():
    assert sp.parse_search_for_card(SNKR, "OP11-106", variant_hint=H_P2) == 751309


def _mit(price, name):
    return {"price": price, "name": "PSA10 " + name, "href": f"https://jp.mercari.com/item/m{price}"}


MERC = [
    _mit(45000, "ゼウス OP11-106 神速の拳 パラレル"),
    _mit(40000, "ゼウス OP11-106 神速の拳"),          # 通常(安い)
]


def test_mercari_parallel_picks_parallel_not_cheapest():
    """通常が安くても、parallel変種が欲しければ parallel を選ぶ(同set print tie-break)。"""
    hint = ["ブースターパック 神速の拳【OP-11】", "神速の拳", "alt_art", "R", "ゼウス"]
    got = mp.pick_cheapest_psa10(MERC, "OP11-106", variant_hint=hint)
    assert got is not None and got[0] == 45000


def test_mercari_normal_picks_normal():
    hint = ["ブースターパック 神速の拳【OP-11】", "神速の拳", "", "R", "ゼウス"]
    got = mp.pick_cheapest_psa10(MERC, "OP11-106", variant_hint=hint)
    assert got is not None and got[0] == 40000
