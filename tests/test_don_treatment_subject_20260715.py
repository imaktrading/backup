#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""番号なし DON!! の treatment 連結 (don_treatment_subject) の回帰テスト (2026-07-15)。

Catalog 回答(2026-07-10): catalog は DON を set+treatment で識別可能(DON-{set}-{NNN})。
真因は生成器が treatment を lookup_don に渡していないこと = HQ の宿題。
本 fix: Vision の rarity(treatment) を subject に連結。treatment 無しは従来どおり fail-closed。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "iMakTCG"))
from psa_to_csv import don_treatment_subject, is_unidentifiable_don_card


def test_don_no_number_with_treatment_enriched():
    # cert 149436908 実データ相当: rarity='Alternate Art Gold'
    v = {"rarity": "Alternate Art Gold", "character": "Mihawk"}
    assert don_treatment_subject("DON!! CARD", "", v) == "DON!! CARD Alternate Art Gold"


def test_don_no_number_without_treatment_none():
    # cert 154458064 実データ相当: rarity='' → 連結不可 → fail-closed skip
    v = {"rarity": "", "character": "Jinbe"}
    assert don_treatment_subject("DON!! CARD", "", v) is None


def test_don_with_number_none():
    # 番号有り DON は従来経路(番号lookup)で解決 → 連結対象外
    v = {"rarity": "Alternate Art Gold"}
    assert don_treatment_subject("DON!! CARD", "DON-PRB01-027", v) is None


def test_not_don_none():
    v = {"rarity": "Alternate Art Gold"}
    assert don_treatment_subject("RORONOA ZORO", "", v) is None


def test_vision_none_none():
    assert don_treatment_subject("DON!! CARD", "", None) is None


def test_treatment_whitespace_only_none():
    assert don_treatment_subject("DON!! CARD", "", {"rarity": "   "}) is None


def test_is_unidentifiable_unchanged():
    # 既存挙動は不変(番号なしDON!!=True / 番号有り=False)
    assert is_unidentifiable_don_card("DON!! CARD", "") is True
    assert is_unidentifiable_don_card("DON!! CARD", "DON-PRB01-027") is False
    assert is_unidentifiable_don_card("RORONOA ZORO", "") is False


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
