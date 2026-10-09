# -*- coding: utf-8 -*-
"""メルカリShops の購入も自動で結ぶ (2026-10-09 ユーザー「自動にしてほしい」)。"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
import mercari_purchases as MP
import order_purchase_sync as O

HTML = ('<a href="https://mercari-shops.com/orders/2JWPi6Q7wmzVyYGR6VPGXP"><p>【PSA10】ピカチュウ PROMO 126/S-P 1枚</p>'
        '<span>2026/09/06 09:19</span></a>'
        '<a href="/transaction/m44733411350"><p>【PSA10】カビゴン R 076/095</p><span>2026/09/13 18:25</span></a>')


def test_parse_shops_and_normal():
    ps = MP.parse_purchases(HTML)
    assert ps[0]["shops"] and ps[0]["url"] == "https://mercari-shops.com/orders/2JWPi6Q7wmzVyYGR6VPGXP"
    assert ps[0]["id"] == "name:" + MP.norm_title("【PSA10】ピカチュウ PROMO 126/S-P 1枚")
    assert ps[0]["at"] == dt.datetime(2026, 9, 6, 9, 19)
    assert ps[1]["id"] == "m44733411350" and not ps[1]["shops"]


def test_shops_key_is_order_id():
    ps = MP.parse_purchases(HTML)
    assert O.purchase_keys(ps, "mercari") == ["shops:2JWPi6Q7wmzVyYGR6VPGXP#1", "mercari:m44733411350#1"]


def test_shops_purchase_matches_by_product_name():
    ps = MP.parse_purchases(HTML)
    cands = {"name:" + MP.norm_title("【PSA10】ピカチュウ　PROMO 126/S-P 1枚")}       # 全角空白の違いは無視
    assert MP.match([(142, dt.date(2026, 9, 5), cands)], ps)[142]["shops"]
