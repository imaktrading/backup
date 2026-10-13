# -*- coding: utf-8 -*-
"""eBay のメールを合図に判断材料を付けて知らせる (2026-10-13 ユーザー「その組み合わせが一番いい」)。"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
import ebay_mail_alert as A  # noqa: E402


def test_kind_and_item_id():
    s = "📩 新しいオファーがあります：PSA 10 Pokemon Japan...（820230435819）をUS $55.00で"
    assert A.kind_of(s) == "offer" and A.item_id_from(s) == "820230435819"
    assert A.kind_of("PSA 10 Pokemon...の支払いがありました") == "paid"
    assert A.kind_of("🏷️ PSA 10 Pokemon...が出品されました") == ""
    assert A.item_id_from("https://www.ebay.com/itm/358514312870?x") == "358514312870"


def test_offer_line_has_profit_supply_and_cheapest():
    o = {"sym": "$", "price": 75, "list": 84.98, "cost": 4777, "supply": 0, "title": "VSTAR", "expire": "2026-10-14 07:27",
         "buyer": "b", "country": "US"}
    t, b = A.offer_line(o, 2459, 4000, 3200)
    assert "利益 ¥2,459" in t and "補URL 0本" in b and "今買える一番安い ¥4,000 → 利益 ¥3,200" in b
    t, b = A.offer_line(dict(o, cost=None), None)
    assert "仕入値なし" in t and "控え無し" in b


def test_paid_line_warns_no_supply():
    assert "🚨仕入元なし" in A.paid_line("x", {"cost": 1000, "n_urls": 0})[1]
    assert "見つかりません" in A.paid_line("x", None)[1]
