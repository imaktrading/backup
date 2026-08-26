# -*- coding: utf-8 -*-
"""C:Attribute/MTG:Color は catalog の color_ebay だけから作る (2026-08-26).

catalog が色を持たない Trainer / Energy 行 (実測 3,998行) に、Vision が読んだ色が
載る口が残っていた。8/25 は日本語だったので日本語ガードが空欄化して助かっただけ。
依頼書: hq/requests/2026-08-25_act_code_proposals_tcg.md 提案3
回答書: hq/requests/2026-08-26_act_code_proposals_tcg_response.md (3)
"""
import io
import os
import sys

_TCG = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "iMakTCG")
if _TCG not in sys.path:
    sys.path.insert(0, _TCG)


def _source(name="psa_to_csv.py"):
    return io.open(os.path.join(_TCG, name), encoding="utf-8").read()


def test_attribute_is_never_filled_from_vision():
    """C:Attribute/MTG:Color の出どころは catalog の color_ebay だけ (契約)。"""
    src = _source()
    assert 'if v.get("color") and not official_color:' not in src, (
        "Vision の色で official_color を補完している。契約は specs.color_ebay だけ "
        "(今回は日本語ガードで助かっただけで、英語なら 'Purple' 等がそのまま出る)")


def test_vision_still_fills_the_fields_it_is_allowed_to():
    """Vision 補完そのものを消したわけではない (card_number 等は従来どおり)。"""
    src = _source()
    assert 'if v.get("character") and not character:' in src, \
        "Vision 補完のブロックごと消えている (範囲を広げすぎ)"
