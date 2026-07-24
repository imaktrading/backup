#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gshock_resource_gate の純ロジック回帰テスト (2026-06-09)。

型番抽出 / id-strict 一致検証 / 価格parse を検証 (Amazon I/O は Selenium=対象外)。
"""
import importlib.util
import os

_MOD = os.path.join(os.path.dirname(__file__), "..", "tools", "gshock_resource_gate.py")
_spec = importlib.util.spec_from_file_location("gshock_resource_gate", _MOD)
g = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(g)


def test_extract_model_full():
    assert g.extract_model("CASIO G-Shock GA-2100FF-8A Mens Analog") == "GA-2100FF-8A"
    assert g.extract_model("CASIO G-SHOCK DW-6900TU-1A5JF Two Tone") == "DW-6900TU-1A5JF"
    assert g.extract_model("CASIO G-SHOCK GBD-200UU-9DR Bluetooth") == "GBD-200UU-9DR"


def test_extract_model_none():
    assert g.extract_model("Casio watch black") is None
    assert g.extract_model("") is None


def test_verify_match_ignores_symbols_case():
    # 記号/大小無視で型番一致
    assert g.verify_match("GA-2100FF-8A", "Casio G-Shock ga2100ff8a Mens Watch") is True
    assert g.verify_match("GA-2100FF-8A", "CASIO GA-2100FF-8A アナデジ") is True


def test_verify_match_rejects_other_model():
    assert g.verify_match("GA-2100FF-8A", "CASIO G-SHOCK DW-5600 Black") is False
    assert g.verify_match("", "anything") is False


def test_parse_price():
    assert g.parse_price("￥ 12,800") == 12800
    assert g.parse_price("価格: ￥9,980 税込") == 9980
    assert g.parse_price("no price") is None


def test_is_amazon_seller_old_phrase():
    assert g.is_amazon_seller("この商品は、Amazon.co.jp が販売、発送します。") is True


def test_is_amazon_seller_tabular():
    assert g.is_amazon_seller("出荷元 Amazon\n販売元 Amazon.co.jp") is True


def test_is_amazon_seller_fba_thirdparty_excluded():
    # FBA: 出荷元Amazon だが 販売元が他社 → 除外
    assert g.is_amazon_seller("出荷元 Amazon\n販売元 ○○ストア") is False


def test_is_amazon_seller_thirdparty_excluded():
    assert g.is_amazon_seller("出荷元 ××商店\n販売元 ××商店") is False
    assert g.is_amazon_seller("") is False


def test_seller_from_text():
    assert g.seller_from_text("出荷元 Amazon\n販売元 Amazon.co.jp") == "Amazon.co.jp"
    assert g.seller_from_text("Amazon.co.jp が販売、発送します") == "Amazon.co.jp"


def test_gshock_wait_ledger_wired_20260724():
    """2026-07-24: End候補/在庫不明を待ち台帳(G-shock再仕入れ待ち)に蓄積する配線が在る。"""
    with open(_MOD, encoding="utf-8") as f:
        src = f.read()
    assert '"G-shock再仕入れ待ち"' in src or "_WAIT_TAB" in src
    assert "psa_restock_wait" in src            # 汎用reconcile を再利用
    assert "held_candidates=_held_list" in src  # 在庫不明も蓄積(孤児化防止)
    assert "_resourceable_ids" in src and "_end_candidates" in src
    # search_error(Amazon到達不可)= held、それ以外の不能 = End候補 の分類
    assert 'startswith("search_error")' in src
