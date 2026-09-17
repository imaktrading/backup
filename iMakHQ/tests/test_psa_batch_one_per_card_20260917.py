# -*- coding: utf-8 -*-
"""PSA 新規の枠に、同じカードを2枚以上入れない (2026-09-17)。

実害: 目視20枠中 S8b-195 ゼクロムが6枠。同じカードは1枚しか出品できないので、枠と目視が無駄だった。
新規出品の目的は「出していない種類を増やす」こと。外した個体は候補に残る (次回以降)。
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_ROOT, "iMakTCG"))

import tcg_batch_select as T  # noqa: E402

NOSHUFFLE = lambda _l: None  # noqa: E731


def test_one_per_card_keeps_order_and_unknown():
    keys = {"a": "S8b-195", "b": "pokemon_tcg:S8b-195", "c": "SV1S-080", "d": "", "e": "s8b-195", "f": ""}
    assert T._one_per_card(list("abcdef"), keys.get) == ["a", "c", "d", "f"]


def test_balanced_sample_fills_slots_with_other_cards():
    certs = [f"z{i}" for i in range(6)] + ["p1", "p2", "p3"]
    tm = {c: "ポケモン PSA10" for c in certs}
    key = {**{f"z{i}": "S8b-195" for i in range(6)}, "p1": "SV1S-080", "p2": "SV1S-013", "p3": "SV9a-077"}
    got = T.balanced_sample(certs, tm, 4, shuffle=NOSHUFFLE, card_of=key.get)
    assert got == ["z0", "p1", "p2", "p3"], got


def test_card_of_rides_on_demand_function():
    def dem(c):
        return 1
    dem.card_of = {"x1": "OP01-001", "x2": "OP01-001", "x3": "OP01-002"}.get
    tm = {c: "ワンピース PSA10" for c in ("x1", "x2", "x3")}
    got = T.balanced_sample(["x1", "x2", "x3"], tm, 3, shuffle=NOSHUFFLE, demand_of=dem)
    assert got.count("x1") + got.count("x2") == 1 and "x3" in got
