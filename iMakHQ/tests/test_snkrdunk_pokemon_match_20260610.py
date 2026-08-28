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


# ★2026-08-28: 採用は「番号一致 かつ set 確証」の両方になった。番号突合そのものは
#   _bracket_matches / _norm_cardnum で見る (このファイルの主題)。採用の可否は別。
#   依頼書: hq/requests/2026-08-28_restock_search_returned_wrong_cards.md
_SVP291 = 'Pikachu P [SV-P 291](Promotional Cards "SV-P")'


def test_pokemon_promo_match_svp():
    """SV-P-291 (catalog KEY) → name [SV-P 291] に番号突合 (484 Pikachu)。"""
    assert sp._bracket_matches(_SVP291.upper(), sp._norm_cardnum("SV-P-291")) is True


def test_pokemon_promo_is_failclosed_without_set():
    """promo は set 名が「Promotional Cards」しか無く確証材料ゼロ → 候補にしない。

    catalog 実測 (2026-08-28): SV-P-291 の hint は set_name_ebay='Promo' だけ。
    OP01-061 (多変種プロモ→手動仕入れ) と同じ扱いに揃える。
    """
    data = {"streetwears": [{"id": 705192, "productNumber": "", "name": _SVP291}]}
    assert sp.set_confirm_tokens(["", "", "Promo"]) == []
    assert sp.parse_search_for_card(data, "SV-P-291", variant_hint=["", "", "Promo"]) is None


def test_pokemon_set_card_match_with_total():
    """SV2a-201 → name [SV2a 201/165] (番号/総数 形式) に突合 + set 確証で採用。"""
    name = 'Charizard ex SAR [SV2a 201/165](Enhanced Expansion Pack "Pokemon Card 151")'
    assert sp._bracket_matches(name.upper(), sp._norm_cardnum("SV2a-201")) is True
    data = {"streetwears": [{"id": 128117, "productNumber": "", "name": name}]}
    hint = ["拡張パック「ポケモンカード151（イチゴーイチ）」", "", "Sv2a: Pokemon Card 151"]
    # 「ポケモンカード」だけでは確証にならない (どの出品にも出る語)
    assert sp.parse_search_for_card(data, "SV2a-201", variant_hint=hint) is None
    named = 'Charizard ex SAR [SV2a 201/165](拡張パック ポケモンカード151 イチゴーイチ)'
    data2 = {"streetwears": [{"id": 128117, "productNumber": "", "name": named}]}
    assert sp.parse_search_for_card(data2, "SV2a-201", variant_hint=hint) == 128117


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
    """同番号 291 で SV-P と SM-P が並んでも、番号突合が当たるのは SV-P の方だけ。

    (採用まで行くには別途 set 確証が要る。ここで見るのは set-code 込みの番号突合。)
    """
    assert sp._bracket_matches('PIKACHU P [SV-P 291](PROMOTIONAL CARDS "SV-P")',
                               sp._norm_cardnum("SV-P-291")) is True
    assert sp._bracket_matches("PIKACHU: PROMO[SM-P 291](SM-P PROMOTIONAL CARDS)",
                               sp._norm_cardnum("SV-P-291")) is False


def test_onepiece_regression_still_matches():
    """既存 OnePiece (productNumber/bracket) 経路が回帰しない (set 確証込み)。"""
    hint11 = ["BOOSTER -A FIST OF DIVINE SPEED- [OP-11]", "ブースターパック 神速の拳【OP-11】",
              "A Fist of Divine Speed"]
    data = {"streetwears": [
        {"id": 520553, "productNumber": "",
         "name": 'Zeus R-P [OP11-106](Booster Pack "A Fist of Divine Speed")'},
    ]}
    assert sp.parse_search_for_card(data, "OP11-106", variant_hint=hint11) == 520553
    hint07 = ["PREMIUM CARD COLLECTION -GIRLS EDITION-", "",
              "Premium Card Collection Girls Edition"]
    data2 = {"streetwears": [
        {"id": 111, "productNumber": "ST07-008",
         "name": "Charlotte Pudding C [ST07-008] ( Premium Card Collection Girls Edition)"},
    ]}
    assert sp.parse_search_for_card(data2, "ST07-008", variant_hint=hint07) == 111


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


def test_resource_card_number_prefers_key_then_title():
    """★2026-08-01 優先順を逆転: KEY(catalog SSOT) 優先 / title は fallback。

    旧実装は title 優先だった。実測 itemID 358604221709 で
    eBayタイトル `#EB01-006`(SR) vs KEY `ST01-006_p1`(C) が食い違い、
    PSA ラベル(25TH ANNIVERSARY PREMIUM CARD COLLECTION)から **KEY が正**と確定。
    title 優先のままだと **別カード(SR)の供給を探して買ってしまう**。
    """
    # 一致していれば当然その番号
    assert gate._resource_card_number("Luffy OP11-106 PSA10", "OP11-106_p1") == "OP11-106"
    # ★食い違ったら KEY を採る (旧実装は title の EB01-006 を返していた)
    assert gate._resource_card_number("Chopper EB01-006 PSA10", "ST01-006_p1") == "ST01-006"
    # KEY から取れない (url-key) → title 由来へ fallback
    assert gate._resource_card_number("Luffy OP11-106 PSA10", "item:999") == "OP11-106"
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
