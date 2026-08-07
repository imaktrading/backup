#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TCG 商品説明への個別 Specifications ブロック挿入の回帰テスト (2026-06-15, 旧コア)。

不変条件:
  - build_tcg_specs_html は **値が空の項目を出さない**(推測なし・出品の正確性)。
  - 1 件も値が無ければ空文字 (= 挿入されない)。
  - insert_tcg_specs は About Color セクション**直前**に挿入し、マーカー/specs 無しなら
    description をそのまま返す (fail-safe = テンプレ変更で壊さない)。
"""
import os
import sys

_TCG = os.path.join(os.path.dirname(__file__), "..", "..", "iMakTCG")
if _TCG not in sys.path:
    sys.path.insert(0, _TCG)


def _mod():
    import psa_to_csv
    return psa_to_csv


def test_specs_skips_empty():
    P = _mod()
    html = P.build_tcg_specs_html([
        ("Card Name", "Pikachu"), ("Set", "Team Up"), ("Card Number", ""),
        ("Rarity", "Promo"), ("Card Type", None), ("Year", "2018"),
    ])
    assert "Pikachu" in html and "Team Up" in html and "Promo" in html and "2018" in html
    assert "Card Number" not in html  # 空欄は出さない
    assert "Card Type" not in html    # None も出さない


def test_specs_empty_when_all_blank():
    P = _mod()
    assert P.build_tcg_specs_html([("Set", ""), ("Rarity", None)]) == ""


def test_insert_before_about_color():
    P = _mod()
    # load_description() は cwd 依存(相対パス)なので、マーカー入り疑似テンプレで挿入を検証
    marker = __import__("tcg_listing_fields")._TCG_SPECS_MARKER
    tmpl = "<ul>...note...</ul>\n" + marker + "...about color...</p>\n...shipping..."
    html = P.build_tcg_specs_html([("Card Name", "Pikachu"), ("Set", "Team Up")])
    out = P.insert_tcg_specs(tmpl, html)
    assert "Specifications" in out
    assert out.find("Specifications") < out.find("About Color")  # About Color の前


def test_insert_failsafe():
    P = _mod()
    # specs 空 → 変更なし
    assert P.insert_tcg_specs("xxx", "") == "xxx"
    # マーカー無し → 変更なし
    assert P.insert_tcg_specs("no marker here", "<p>Specs</p>") == "no marker here"


def _tlf():
    import tcg_listing_fields
    return tcg_listing_fields


def test_replace_tcg_specs_swaps_old_for_new():
    # 新コア override が旧 Specs を除去して新値で作り直す
    T = _tlf()
    marker = T._TCG_SPECS_MARKER
    old = "head" + T.build_tcg_specs_html([("Card Name", "OLD"), ("Set", "OLDSET")]) + marker + "tail"
    new = T.replace_tcg_specs(old, T.build_tcg_specs_html([("Card Name", "Pikachu")]))
    assert "OLD" not in new and "OLDSET" not in new   # 旧 Specs 除去
    assert "Pikachu" in new                            # 新 Specs 挿入
    assert new.count("Specifications") == 1            # 重複しない


def test_specs_pairs_from_fields():
    T = _tlf()
    pairs = dict(T.specs_pairs_from_fields(
        {"C:Card Name": "Pikachu", "C:Set": "Team Up", "C:Card Number": "307/SM-P", "C:Language": ""}))
    assert pairs["Card Name"] == "Pikachu"
    assert pairs["Set"] == "Team Up"
    assert pairs["Card Number"] == "307/SM-P"
    # 2026-06-15 改訂: C:Language 空は空のまま (無条件 Japanese 埋め廃止・誤表示防止/fail-closed)。
    assert pairs["Language"] == ""
    # 日本語カードは C:Language='Japanese' をそのまま転記
    pairs2 = dict(T.specs_pairs_from_fields({"C:Card Name": "X", "C:Language": "Japanese"}))
    assert pairs2["Language"] == "Japanese"
