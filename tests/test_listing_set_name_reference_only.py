# -*- coding: utf-8 -*-
"""#1b 回帰防止: 出品は set_name を catalog の set_name_ebay から「参照のみ」。
出品時の再変換 (set_code_to_ebay_name / _dragonball_set_name_to_ebay) を復活させない。

背景(2026-06-08): カタログ=正の辞書(SSOT)、出品は参照するだけ、という設計。
旧コードは出品の度に set 名を再変換しており「毎回作り出す」=変換層バグの伝播源だった。
Catalog #1a で set_name_ebay を clean 保存したので出品側の再変換は撤去済。
この変換呼び出しが再混入したらこのテストが落ちる。
"""
import pathlib


def _src():
    p = pathlib.Path(__file__).resolve().parent.parent / "iMakTCG" / "psa_to_csv.py"
    return p.read_text(encoding="utf-8")


def test_no_set_name_reconversion_in_listing():
    text = _src()
    # 撤去した「出品時 set_name 再変換」呼び出しが復活していないこと
    assert "set_code_to_ebay_name(set_name)" not in text, (
        "出品時の set_name 再変換が復活している (参照のみ原則に違反)"
    )
    assert "_dragonball_set_name_to_ebay(set_name)" not in text, (
        "Dragon Ball set_name 再変換が復活している (参照のみ原則に違反)"
    )


def test_set_name_sourced_from_catalog_set_name_ebay():
    text = _src()
    # 参照元 = catalog lookup の set_name_ebay であること (主要ブランチに存在)
    assert 'set_name = bandai["set_name_ebay"]' in text
    assert 'set_name = pokemon["set_name_ebay"]' in text
