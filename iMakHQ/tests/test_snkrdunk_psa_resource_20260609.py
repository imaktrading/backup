#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""snkrdunk_psa_resource.parse_min_prices の回帰テスト (2026-06-09)。

SNKRDUNK API /en/v1/trading-cards/{card_id}/min-prices-by-conditions のレスポンスから
PSA10 の最安を抽出し再仕入れ可否を出す parser を検証。ネット不要 (実構造のフィクスチャ)。
"""
import importlib.util
import os

_MOD = os.path.join(os.path.dirname(__file__), "..", "tools", "snkrdunk_psa_resource.py")
_spec = importlib.util.spec_from_file_location("snkrdunk_psa_resource", _MOD)
sp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sp)

# 実APIレスポンス構造 (card 676020 の実観測値ベース)
FIXTURE = {"conditionPrices": [
    {"conditionId": 20, "conditionName": "C", "minPrice": 1800, "minPriceFormat": "¥1,800"},
    {"conditionId": 18, "conditionName": "A", "minPrice": 4400, "minPriceFormat": "¥4,400"},
    {"conditionId": 19, "conditionName": "B", "minPrice": 2500, "minPriceFormat": "¥2,500"},
    {"conditionId": 22, "conditionName": "PSA 10", "minPrice": 32800, "minPriceFormat": "¥32,800"},
]}


def test_psa10_available_with_price():
    r = sp.parse_min_prices(FIXTURE)
    assert r["available"] is True
    assert r["psa10_price_jpy"] == 32800


def test_conditions_all_captured():
    r = sp.parse_min_prices(FIXTURE)
    assert r["conditions"]["PSA 10"] == 32800
    assert r["conditions"]["A"] == 4400
    assert set(r["conditions"].keys()) == {"C", "A", "B", "PSA 10"}


def test_no_psa10_when_absent():
    data = {"conditionPrices": [
        {"conditionName": "A", "minPrice": 2300, "minPriceFormat": "¥2,300"},
        {"conditionName": "PSA 9", "minPrice": 1790000, "minPriceFormat": "¥1,790,000"},
    ]}
    r = sp.parse_min_prices(data)
    assert r["available"] is False
    assert r["psa10_price_jpy"] is None


def test_empty_response():
    r = sp.parse_min_prices({"conditionPrices": []})
    assert r["available"] is False and r["psa10_price_jpy"] is None


def test_resolve_search_match_by_bracket():
    """search レスポンスから [CARD番号] を含む name で id 突合 (id-strict)。"""
    data = {"streetwears": [
        {"id": 999, "productNumber": "", "name": "Other R-P [OP99-999](X)"},
        {"id": 520553, "productNumber": "", "name": "Zeus R-P [OP11-106](Booster Pack)"},
    ], "sneakers": []}
    assert sp.parse_search_for_card(data, "OP11-106") == 520553


def test_resolve_match_by_product_number():
    data = {"streetwears": [{"id": 111, "productNumber": "ST07-008", "name": "Pudding"}]}
    assert sp.parse_search_for_card(data, "ST07-008") == 111


def test_resolve_no_match_returns_none():
    """誤マッチ防止: 一致が無ければ None (fail-closed)。"""
    data = {"streetwears": [{"id": 1, "productNumber": "", "name": "Zoro [OP15-113]"}]}
    assert sp.parse_search_for_card(data, "OP11-106") is None


def test_malformed_safe():
    r = sp.parse_min_prices({})
    assert r["available"] is False
    r2 = sp.parse_min_prices({"conditionPrices": [{"conditionName": "PSA 10"}]})  # minPrice欠落
    assert r2["available"] is False and r2["psa10_price_jpy"] is None
