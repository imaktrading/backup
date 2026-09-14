# -*- coding: utf-8 -*-
"""売れて在庫0のまま残った出品を「売れた分を補充」で拾う (2026-09-14)。

実害: 売れた25件のうち4出品が在庫0のまま。台帳 B列に番号があるだけで「補充済」とされ、
一覧にもボタンの件数にも出ず、押しても何もしなかった。監視くんは仕入元が売切→在庫ありに
戻った時しか数量を戻さないので、仕入元が売れていない出品は誰も戻さない。
同じ日に見つかったこと:
  - GetItem の Quantity は総数。在庫0でも Quantity=1 / QuantitySold=1 → 残りは差で出す
  - AU のミラーで売れると注文の番号はミラー。数量を戻す相手は台帳の US の出品
  - pricing のカテゴリ名 "G-shock" / "Ichibankuji" は存在せず、G-SHOCK の売上1件で落ちた
"""
import os
import sys

HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HQ, "tools"))
sys.path.insert(0, r"C:\dev\iMak\iMakeBayAPI")

import sold_restock as R                # noqa: E402
import sold_restock_worklist as W       # noqa: E402

B = W.S.PRODUCT_COL_ITEMID


def _row(item_id):
    r = [""] * 40
    r[B] = item_id
    return r


def test_ledger_listing_with_zero_stock_is_not_restocked():
    live = {"820065007508": {"avail": 0, "site": "US"}, "358737984346": {"avail": 1, "site": "US"}}
    assert W.classify(_row("820065007508"), live=live)[0] == "在庫0"
    assert W.classify(_row("358737984346"), live=live)[0] == "補充済"
    assert W.classify(_row("999"), live=live)[0] == "出品なし"
    assert W.classify(_row(""), live=live)[0] == "未補充"
    assert W.classify(_row("820065007508"))[0] == "補充済"          # live 無しは従来どおり


def test_restock_acts_on_the_us_ledger_listing_not_the_mirror():
    assert R.restock_target("在庫0", _row("820041237462"), "820041751397") == "820041237462"
    assert R.restock_target("未補充", _row(""), "358000000001") == "358000000001"


def test_zero_stock_listing_does_not_block_itself_as_already_live():
    KEY = W.S.PRODUCT_COL_KEY
    r = _row("820065007508")
    r[KEY] = "pokemon_tcg:SV5a-067"
    sheets = [("スプシ1", [["h"], r])]
    assert R.live_keys(sheets, {"820065007508": {"avail": 0}}) == set()
    assert R.live_keys(sheets, {"820065007508": {"avail": 1}}) == {"pokemon_tcg:SV5a-067"}


# 2026-09-14 実機の GetItem 応答 (要素だけ抜粋)
US_ZERO = ("<Item><Seller><Site>US</Site></Seller><Quantity>1</Quantity><SellingStatus>"
           "<ListingStatus>Active</ListingStatus><QuantitySold>1</QuantitySold></SellingStatus>"
           "<ShippingDetails></ShippingDetails><ShipToLocations>Worldwide</ShipToLocations><Site>US</Site></Item>")
AU_MIRROR = ("<Item><Seller><Site>US</Site></Seller><Quantity>1</Quantity><SellingStatus>"
             "<ListingStatus>Active</ListingStatus><QuantitySold>1</QuantitySold></SellingStatus>"
             "<ShipToLocations>AU</ShipToLocations><Site>Australia</Site></Item>")


def test_getitem_zero_stock_is_quantity_minus_sold():
    assert R.parse_item_status(US_ZERO) == ("Active", 0, "US")
    assert R.plan_action("Active", 0) == "revise"


def test_getitem_site_is_the_listing_site_not_the_seller_site():
    assert R.parse_item_status(AU_MIRROR)[2] == "Australia"
    assert R.parse_item_status("") == ("?", -1, "?")


def test_pricing_categories_exist():
    import pricing_engine as P
    for cat, key in R.CATEGORY_FOR_PRICING.items():
        assert P.get_category_params(key), (cat, key)
