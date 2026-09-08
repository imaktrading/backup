# -*- coding: utf-8 -*-
"""版の手がかりが無い時に「通常版」と決めつけない (2026-09-08)。

同じ番号で 通常 / パラレル / SP が並ぶのは実測で **120件中80件 (67%)**。
決めつけると平気で別の版を掴む。実例 PRB02-014 (サボ):

    656343  Sabo SR-P  [PRB02-014](Premium Booster The Best vol.2)  ← 実物はこちら
    653499  Sabo SR    [PRB02-014](Premium Booster The Best vol.2)  ← 道具はこちらを返した

この id は 補URL の点検だけでなく **再仕入れの在庫判定と最安値の取得**にも使われるので、
取り違えると別の版の値段で cost-plus が回る = 安く売る事故につながる。
"""
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "iMakHQ", "tools")))

import snkrdunk_psa_resource as sp   # noqa: E402


def test_no_hint_at_all_is_unknown_not_normal():
    """空 = 何も分からない。'通常' と答えない。"""
    assert sp._print_signal(None) is None
    assert sp._print_signal("") is None
    assert sp._print_signal(["", "", ""]) is None


def test_rarity_without_parallel_marks_is_still_normal():
    """rarity 等が在って パラレルの印が無い = 『通常だと分かっている』。従来どおり ''。"""
    assert sp._print_signal(["ブースターパック", "SR", "ルフィ"]) == ""


def test_parallel_and_special_are_detected():
    assert sp._print_signal(["alt_art", "SR"]) == "P"
    assert sp._print_signal(["SPカード"]) == "SPC"
    assert sp._print_signal(["L*"]) == "P"          # Dragon Ball の * = パラレル


def _search(names):
    return {"streetwears": [{"id": 100 + i, "name": nm, "productNumber": ""}
                            for i, nm in enumerate(names)]}


def test_unknown_print_does_not_pick_among_multiple(monkeypatch):
    """同じ set に複数 print が在り、こちらの版が不明なら **選ばない** (fail-closed)。"""
    data = _search(['Sabo SR-P [PRB02-014](Premium Booster "One Piece Card The Best vol.2")',
                    'Sabo SR [PRB02-014](Premium Booster "One Piece Card The Best vol.2")'])
    got = sp._match_item(data, "PRB02-014",
                         variant_hint=['Premium Booster "One Piece Card The Best vol.2"'])
    assert got is None


def test_known_parallel_picks_the_parallel(monkeypatch):
    data = _search(['Sabo SR-P [PRB02-014](Premium Booster "One Piece Card The Best vol.2")',
                    'Sabo SR [PRB02-014](Premium Booster "One Piece Card The Best vol.2")'])
    got = sp._match_item(data, "PRB02-014",
                         variant_hint=['Premium Booster "One Piece Card The Best vol.2"',
                                       "alt_art"])
    assert got and got["name"].startswith("Sabo SR-P")
