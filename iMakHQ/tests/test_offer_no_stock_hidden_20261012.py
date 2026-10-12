# -*- coding: utf-8 -*-
"""在庫0の出品のオファーは出さない (2026-10-12)。

親 (US 820209548828) が売れて在庫0になったカナダのミラー 820215140714 に、オファーが
「受信中」のまま残っていた (eBay は在庫0でもオファーを取り消さない)。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import offer_calc as O  # noqa: E402


def test_zero_stock():
    assert O.available_qty("<Item><Quantity>1</Quantity><SellingStatus><QuantitySold>1</QuantitySold>"
                           "</SellingStatus></Item>") == 0
    assert O.available_qty("<Item><Quantity>0</Quantity></Item>") == 0


def test_in_stock():
    assert O.available_qty("<Item><Quantity>1</Quantity><SellingStatus><QuantitySold>0</QuantitySold>"
                           "</SellingStatus></Item>") == 1


def test_unreadable_is_not_hidden():
    assert O.available_qty("") is None
    assert O.available_qty("<Ack>Failure</Ack>") is None


def test_list_and_count_both_filter():
    src = open(os.path.join(os.path.dirname(__file__), "..", "tools", "offer_calc.py"), encoding="utf-8").read()
    assert src.count("available_qty(") >= 3          # 定義 + 画面 + 件数
    assert "在庫0の出品のオファーは出さない" in src
