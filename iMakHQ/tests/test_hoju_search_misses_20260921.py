# -*- coding: utf-8 -*-
"""2026-09-21 補URL 0本の「候補はあったのに全部落ちた」25件の原因3つ。

1. メルカリShops はログイン無しだと checkout-button が出ない → 全部「買えない」扱いだった
2. 検索は 177/165 で引くのに照合に market_no を渡していなかった
3. 177/165 表記のカードは set コード(SV2a/SV-P)+番号で確証できるのに set 名必須だった
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
import mercari_psa_resource as mp

SHOPS_OK = '<p data-testid="quantity">在庫残り1点</p><div><button type="button" aria-label="ログイン">購入手続きへ</button></div>'
SHOPS_SOLD = '<p>売り切れ</p><div testid="disabled-purchase-button"><button type="button" disabled="" data-testid="disabled-purchase-button">購入手続きへ</button></div>'


def test_shops_logged_out_is_buyable():
    assert mp.buyable_from_detail(SHOPS_OK) is True


def test_shops_sold_is_not_buyable():
    assert mp.buyable_from_detail(SHOPS_SOLD) is False


def test_bid_button_still_not_buyable():
    assert mp.buyable_from_detail('<button data-testid="bid-button">入札</button>' + SHOPS_OK) is False


def _it(n):
    return [{"price": 1000, "href": "https://jp.mercari.com/item/m1", "name": n}]


def test_slash_number_with_set_code_confirms():
    assert mp._variant_matches(_it("【PSA10】ゴーリキー AR SV2a 177/165"), "SV2A-177", ["x"], "177/165")


def test_slash_number_without_code_or_set_still_rejected():
    assert mp._variant_matches(_it("【PSA10】ゴーリキー AR 177/165"), "SV2A-177", ["x"], "177/165") == []


def test_code_alone_without_number_rejected():
    assert mp._variant_matches(_it("【PSA10】ゴーリキー AR SV2a"), "SV2A-177", ["x"], "177/165") == []


def test_similar_code_prefix_does_not_confirm():
    # SM7 のカードに SM7a と書いた出品 = 別セット
    assert mp._variant_matches(_it("PSA10 バシャーモ SM7a 098/096"), "SM7-098", ["x"], "098/096") == []


def test_promo_sv_p_not_read_as_parallel():
    assert mp._variant_matches(_it("【PSA10】ピカチュウ 291/SV-P げきとうスパーク"), "SV-P-291", [], "291/SV-P")


def test_hyphen_number_cards_unchanged():
    # ワンピ等は market_no に / が無い = 従来どおり set 名が要る
    assert mp._variant_matches(_it("PSA10 フランキー ST29-010"), "ST29-010", ["x"], "ST29-010") == []
