#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SNKRDUNK Pokemon 突合の回帰テスト (2026-06-10)。

Pokemon は productNumber が空で番号が name の `[SV-P 291]`/`[SV2a 201/165]` に埋まる。
区切り差(空白/ハイフン)・総数(/165)を吸収する _norm_cardnum / _bracket_matches を検証。
set-code prefix 差(catalog 'S8a' ↔ SNKRDUNK 'SV8a' 等)は no-match=fail-closed(誤マッチさせない)。
ネット不要 (実観測の name 形のフィクスチャ)。
"""
import importlib.util
import os

_MOD = os.path.join(os.path.dirname(__file__), "..", "tools", "snkrdunk_psa_resource.py")
_spec = importlib.util.spec_from_file_location("snkrdunk_psa_resource", _MOD)
sp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sp)


def test_norm_cardnum_variants():
    assert sp._norm_cardnum("SV-P-291") == "SVP291"
    assert sp._norm_cardnum("SV2a 201/165") == "SV2A201"   # 総数(/165)除去
    assert sp._norm_cardnum("OP11-106") == "OP11106"
    assert sp._norm_cardnum("") == ""


def test_pokemon_promo_match_svp():
    """SV-P-291 (catalog KEY) → name [SV-P 291] に突合 (484 Pikachu)。"""
    data = {"streetwears": [
        {"id": 705192, "productNumber": "", "name": 'Pikachu P [SV-P 291](Promotional Cards "SV-P")'},
    ], "sneakers": []}
    assert sp.parse_search_for_card(data, "SV-P-291") == 705192


def test_pokemon_set_card_match_with_total():
    """SV2a-201 → name [SV2a 201/165] (番号/総数 形式) に突合。"""
    data = {"streetwears": [
        {"id": 128117, "productNumber": "", "name": "Charizard ex SAR [SV2a 201/165](Enhanced Expansion Pack)"},
    ]}
    assert sp.parse_search_for_card(data, "SV2a-201") == 128117


def test_pokemon_setcode_prefix_diff_failclosed():
    """catalog 'S8a-207' は SNKRDUNK 'SV8a' と prefix 差 → no-match (誤マッチさせない)。"""
    data = {"streetwears": [
        {"id": 1, "productNumber": "", "name": "Teal Mask Ogerpon ex SAR [SV8a 207/187](High Class)"},
    ]}
    assert sp.parse_search_for_card(data, "S8a-207") is None


def test_pokemon_promo_series_not_confused():
    """SV-P-291 が別シリーズ SM-P 291 に誤マッチしない (set-code 完全一致のみ)。"""
    data = {"streetwears": [
        {"id": 2, "productNumber": "", "name": "Pikachu: PROMO[SM-P 291](SM-P Promotional cards)"},
    ]}
    assert sp.parse_search_for_card(data, "SV-P-291") is None


def test_pokemon_picks_correct_among_multiple():
    """同番号 291 で SV-P と SM-P が並ぶ中、SV-P-291 は SV-P の方を選ぶ。"""
    data = {"streetwears": [
        {"id": 705192, "productNumber": "", "name": 'Pikachu P [SV-P 291](Promotional Cards "SV-P")'},
        {"id": 9, "productNumber": "", "name": "Pikachu: PROMO[SM-P 291](SM-P Promotional cards)"},
    ]}
    assert sp.parse_search_for_card(data, "SV-P-291") == 705192


def test_onepiece_regression_still_matches():
    """既存 OnePiece (productNumber/bracket) 経路が回帰しない。"""
    data = {"streetwears": [
        {"id": 520553, "productNumber": "", "name": "Zeus R-P [OP11-106](Booster Pack)"},
    ]}
    assert sp.parse_search_for_card(data, "OP11-106") == 520553
    data2 = {"streetwears": [{"id": 111, "productNumber": "ST07-008", "name": "Pudding"}]}
    assert sp.parse_search_for_card(data2, "ST07-008") == 111


# ---- gate 側 KEY→card番号 導出 ----
_GATE = os.path.join(os.path.dirname(__file__), "..", "tools", "psa_resource_gate.py")
_gspec = importlib.util.spec_from_file_location("psa_resource_gate", _GATE)
gate = importlib.util.module_from_spec(_gspec)
_gspec.loader.exec_module(gate)


def test_key_card_number_derivation():
    assert gate._key_card_number("SV-P-291") == "SV-P-291"
    assert gate._key_card_number("OP11-106_p2") == "OP11-106"   # 変種suffix除去
    assert gate._key_card_number("item:123") is None            # url-key 除外
    assert gate._key_card_number("shops:abc") is None
    assert gate._key_card_number("") is None


def test_resource_card_number_prefers_title_then_key():
    # OnePiece: title に番号 → title 由来
    assert gate._resource_card_number("Luffy OP11-106 PSA10", "OP11-106_p1") == "OP11-106"
    # Pokemon: title 日本語(番号無) → KEY 由来
    assert gate._resource_card_number("ポケモンカード ピカチュウ PSA10", "SV-P-291") == "SV-P-291"
    # 番号源が無い → None (fail-closed)
    assert gate._resource_card_number("ポケモンカード PSA10", "item:999") is None


# ---- 補URL: SNKRDUNK PSA10出品を複数(最安の代替候補)返す ----
def test_combine_fills_multiple_aux_urls_from_snkrdunk():
    """check_by_keyword の psa10_listings (価格昇順 複数) が補URLに展開される。
    最安1件だけだと最安値列と重複し補URLの意味が無い→2件目以降が代替候補として入る。"""
    snk = {"available": True, "psa10_price_jpy": 22000, "card_id": 129628,
           "card_url": "https://snkrdunk.com/apparels/129628/used/1",
           "psa10_listings": [
               {"price": 22000, "url": "https://snkrdunk.com/apparels/129628/used/1"},
               {"price": 23000, "url": "https://snkrdunk.com/apparels/129628/used/2"},
               {"price": 25000, "url": "https://snkrdunk.com/apparels/129628/used/3"},
           ]}
    c = gate.combine(None, snk)
    assert c["resourceable"] is True
    assert c["snkrdunk_jpy"] == 22000
    assert c["snkrdunk_count"] == 3                    # 複数件カウント
    assert len(c["snkrdunk_urls"]) == 3                # 補URLが3件 (最安+代替2)
    assert [u["price"] for u in c["snkrdunk_urls"]] == [22000, 23000, 25000]


def test_combine_backward_compat_single_card_url():
    """psa10_listings 無 (旧shape) でも card_url 1件にフォールバック。"""
    snk = {"available": True, "psa10_price_jpy": 30000, "card_id": 5,
           "card_url": "https://snkrdunk.com/apparels/5"}
    c = gate.combine(None, snk)
    assert c["resourceable"] is True
    assert len(c["snkrdunk_urls"]) == 1
    assert c["snkrdunk_urls"][0]["url"] == "https://snkrdunk.com/apparels/5"


def test_check_by_keyword_builds_multiple_listings(monkeypatch):
    """check_by_keyword が PSA10出品を価格昇順で複数 psa10_listings に組む (最安だけにしない)。"""
    monkeypatch.setattr(sp, "resolve_card_id", lambda *a, **k: 129628)
    monkeypatch.setattr(sp, "fetch_psa10_listings", lambda *a, **k: [
        {"listing_id": 1, "price": 22000},
        {"listing_id": 2, "price": 23000},
    ])
    res = sp.check_by_keyword("ST07-008")
    assert res["available"] is True
    assert res["psa10_price_jpy"] == 22000
    assert len(res["psa10_listings"]) == 2
    assert res["psa10_listings"][1]["url"].endswith("/used/2")
