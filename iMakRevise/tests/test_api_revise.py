"""api_revise (API 版・影運用) のテスト. eBay には送らない."""
import json

import pytest

from revise.api_revise import (ShippingChange, PriceChange, assert_only_allowed_tags,
                               build_all_xml, build_plan, build_shipping_xml)

HDR_SINGLE = '"*Action(SiteID=US|Country=JP|Currency=USD|Version=745|CC=UTF-8)","ItemID","ShippingProfileName","*StartPrice","BestOfferAutoAcceptPrice","MinimumBestOfferPrice"\n'
HDR_VP = '"*Action(SiteID=US|Country=JP|Currency=USD|Version=745|CC=UTF-8)","ItemID","Relationship","RelationshipDetails","*StartPrice"\n'
HDR_VS = '"*Action(SiteID=US|Country=JP|Currency=USD|Version=745|CC=UTF-8)","ItemID","ShippingProfileName"\n'


def _w(p, text):
    p.write_text(text, encoding="utf-8")
    return p


def test_plan_maps_variation_to_sku_and_policy_to_id(tmp_path):
    single = _w(tmp_path / "s.csv", HDR_SINGLE + '"Revise","111","DDP-A-P22","366.98","",""\n')
    vp = _w(tmp_path / "vp.csv", HDR_VP
            + '"Revise","222","","Color=Black|Sizes=US S(JP M)",""\n'
            + '"","","Variation","Sizes=US S(JP M)|Color=Black","100.98"\n')
    vs = _w(tmp_path / "vs.csv", HDR_VS + '"Revise","222","DDP-C-P11"\n')
    snap = _w(tmp_path / "v.json", json.dumps(
        {"222": [{"sku": "SKU-1", "specifics": {"Color": "Black", "Sizes": "US S(JP M)"}}]}))
    plan = build_plan(single, vp, vs, snap, {"DDP-A-P22": "9001", "DDP-C-P11": "9002"})
    assert plan.problems == []
    assert {(c.item_id, c.sku, c.price) for c in plan.prices} == {("111", None, 366.98), ("222", "SKU-1", 100.98)}
    assert {(s.item_id, s.profile_id) for s in plan.shippings} == {("111", "9001"), ("222", "9002")}
    assert len(build_all_xml(plan)) == 3  # 値段1呼出(2件) + 送料2呼出


def test_unknown_sku_or_policy_goes_to_problems_not_guessed(tmp_path):
    vp = _w(tmp_path / "vp.csv", HDR_VP + '"Revise","222","",""," "\n'
            + '"","","Variation","Color=Red","50.98"\n')
    vs = _w(tmp_path / "vs.csv", HDR_VS + '"Revise","222","DDP-X"\n')
    snap = _w(tmp_path / "v.json", json.dumps({"222": [{"sku": "S", "specifics": {"Color": "Black"}}]}))
    plan = build_plan(None, vp, vs, snap, {})
    assert plan.prices == []
    assert len(plan.problems) == 2


def test_single_row_on_variation_listing_is_rejected(tmp_path):
    single = _w(tmp_path / "s.csv", HDR_SINGLE + '"Revise","222","DDP-A-P22","10.98","",""\n')
    snap = _w(tmp_path / "v.json", json.dumps({"222": [{"sku": "S", "specifics": {"Color": "Black"}}]}))
    plan = build_plan(single, None, None, snap, {"DDP-A-P22": "1"})
    assert plan.prices == [] and plan.problems


def test_xml_carries_only_price_or_shipping_profile():
    x = build_shipping_xml(ShippingChange("111", "DDP-A-P22", "9001"))
    assert_only_allowed_tags(x)
    assert "ItemSpecifics" not in x and "Quantity" not in x and "Title" not in x
    with pytest.raises(ValueError):
        assert_only_allowed_tags(x.replace("</Item>", "<ItemSpecifics></ItemSpecifics></Item>"))
    from revise.api_revise import build_inventory_status_xml
    y = build_inventory_status_xml([PriceChange("111", 12.5)])
    assert_only_allowed_tags(y)
    assert "<StartPrice>12.50</StartPrice>" in y and "Quantity" not in y
