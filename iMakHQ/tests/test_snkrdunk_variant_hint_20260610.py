# -*- coding: utf-8 -*-
"""Step6 P3: SNKRDUNK parse_search_for_card が canonical変種 hint で複数 print を正選択 + fail-closed."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import snkrdunk_psa_resource as sp


def _data(*items):
    return {"tradingCards": list(items)}


def test_single_match_resolves():
    d = _data({"id": 111, "productNumber": "OP08-106", "name": "ナミ [OP08-106]"})
    assert sp.parse_search_for_card(d, "OP08-106") == 111


def test_no_match_failclosed():
    d = _data({"id": 1, "productNumber": "OP01-001", "name": "ルフィ"})
    assert sp.parse_search_for_card(d, "OP11-106") is None


def test_multi_print_no_hint_failclosed():
    """同番号に複数 print・hint無 → 誤variant回避で None。"""
    d = _data(
        {"id": 520553, "productNumber": "OP11-106", "name": "ゼウス [OP11-106] 神速の拳"},
        {"id": 498160, "productNumber": "OP11-106", "name": "ゼウス [OP11-106] 二つの伝説"},
    )
    assert sp.parse_search_for_card(d, "OP11-106") is None


def test_multi_print_hint_picks_right():
    """hint(set=神速の拳)で正しい print を一意選択。"""
    d = _data(
        {"id": 520553, "productNumber": "OP11-106", "name": "ゼウス [OP11-106] 神速の拳"},
        {"id": 498160, "productNumber": "OP11-106", "name": "ゼウス [OP11-106] 二つの伝説"},
    )
    got = sp.parse_search_for_card(d, "OP11-106", variant_hint=["神速の拳 OP-11", "ゼウス", "OP11-106"])
    assert got == 520553


def test_multi_print_hint_tie_failclosed():
    """hint が両方に等しく当たる(同点) → 一意でないため None。"""
    d = _data(
        {"id": 1, "productNumber": "P-041", "name": "ルフィ [P-041] プロモ"},
        {"id": 2, "productNumber": "P-041", "name": "ルフィ [P-041] プロモ"},
    )
    got = sp.parse_search_for_card(d, "P-041", variant_hint=["プロモ", "ルフィ"])
    assert got is None


def test_hint_no_overlap_failclosed():
    """hint が複数一致のどれにも当たらない → 決め手無で None。"""
    d = _data(
        {"id": 1, "productNumber": "OP11-106", "name": "ゼウス [OP11-106] 神速の拳"},
        {"id": 2, "productNumber": "OP11-106", "name": "ゼウス [OP11-106] 二つの伝説"},
    )
    got = sp.parse_search_for_card(d, "OP11-106", variant_hint=["全然違うセット名XYZ"])
    assert got is None
