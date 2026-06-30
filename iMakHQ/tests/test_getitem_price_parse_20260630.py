# -*- coding: utf-8 -*-
"""ebay_getitem_images._parse_getitem_price: 現価格をUSD換算で取る回帰テスト (2026-06-30)。

non-US出品(AUD/EUR/GBP)は ConvertedCurrentPrice(USD)を価格に、native通貨も返す。
funnel/レポートのstale価格でなく GetItem ライブで取得する設計。
"""
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "iMakeBayAPI")))
import ebay_getitem_images as g


def test_non_us_uses_converted_usd():
    # AUD出品: native=AUD 357.89 だが USD換算 246.96 を価格に
    xml = ('<CurrentPrice currencyID="AUD">357.89</CurrentPrice>'
           '<ConvertedCurrentPrice currencyID="USD">246.96</ConvertedCurrentPrice>')
    price, ccy = g._parse_getitem_price(xml)
    assert price == 246.96
    assert ccy == "AUD"


def test_us_listing_usd():
    xml = ('<CurrentPrice currencyID="USD">99.99</CurrentPrice>'
           '<ConvertedCurrentPrice currencyID="USD">99.99</ConvertedCurrentPrice>')
    price, ccy = g._parse_getitem_price(xml)
    assert price == 99.99 and ccy == "USD"


def test_no_converted_falls_back_to_current():
    xml = '<CurrentPrice currencyID="USD">50.00</CurrentPrice>'
    price, ccy = g._parse_getitem_price(xml)
    assert price == 50.0 and ccy == "USD"


def test_empty_returns_none():
    assert g._parse_getitem_price("") == (None, None)
    assert g._parse_getitem_price("<NoPrice/>") == (None, None)
