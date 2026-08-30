# -*- coding: utf-8 -*-
"""売れた → 補充 (2026-08-28 新設)。

ユーザー確定: 「単純に在庫1にして、仕入れ値で価格とポリシーを変えるだけ」。
作り直さない (窓口が作り直したら値段が $100 で出た。正しくは $120.98)。

守ること:
  - Completed=relist / Active qty=0=revise / Active qty>0=触らない / 不明=触らない
  - 価格が取れない時は **その要素を送らない** (0 で上書きすると赤字出品になる)
  - アパレルは対象に入れない (公式在庫が戻れば監視くんが復活させる)
"""
from __future__ import annotations

import os
import sys

HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HQ, "tools"))

import sold_restock as R                                          # noqa: E402
import sold_restock_worklist as W                                 # noqa: E402


class TestWhatToDo:
    def test_売れて終了なら_relist(self):
        assert R.plan_action("Completed", 0) == "relist"

    def test_生きていて在庫0なら_revise(self):
        assert R.plan_action("Active", 0) == "revise"

    def test_生きていて在庫ありなら_触らない(self):
        assert R.plan_action("Active", 1) == "noop"

    def test_状態不明なら_触らない(self):
        assert R.plan_action("?", -1) == "skip"


class TestXml:
    def test_数量と価格と送料ポリシーを一緒に送る(self):
        x = R.build_item_xml("820012345678", 120.98, "DDP-A-P12")
        assert "<Quantity>1</Quantity>" in x
        assert "<StartPrice>120.98</StartPrice>" in x
        assert "<ShippingProfileName>DDP-A-P12</ShippingProfileName>" in x

    def test_価格が取れない時は価格を送らない(self):
        x = R.build_item_xml("820012345678", None, None)
        assert "<Quantity>1</Quantity>" in x
        assert "StartPrice" not in x and "ShippingProfileName" not in x


class TestCategory:
    def test_PSAとGShockと一番くじが対象(self):
        assert W.category_of("PSA 10 Pokemon Japanese Sv9 #105 Lillie's Ribombee") == "PSA"
        assert W.category_of("CASIO G-Shock GA-010GGB-1A9 Mens Watch") == "G-Shock"
        assert W.category_of("Ichiban Kuji JoJo B Prize Crazy Diamond") == "一番くじ"

    def test_アパレルは対象外(self):
        # 監視くんが公式在庫で戻すので、こちらで触ると二重出品になる
        assert W.category_of("UNIQLO UT Pokemon 30th Anniversary Bulbasaur Tee") == ""
        assert W.category_of("GU Hiromichi Yokochi Sukajan Dragon T-Shirt") == ""

    def test_一点ものは対象外(self):
        assert W.category_of("YOSHIDA PORTER Tanker Shoulder Bag L Black Pre-owned") == ""
        assert W.category_of("Masudaya R-120 Silver Steam Train Wind-Up Tin Toy Vintage") == ""


class TestLedgerRow:
    def test_B列にitemIDがあれば補充済(self):
        row = [""] * 40
        row[W.S.PRODUCT_COL_ITEMID] = "820057587485"
        assert W.classify(row)[0] == "補充済"

    def test_B列が空なら未補充で補URLを返す(self):
        row = [""] * 40
        row[W.AUX] = "https://jp.mercari.com/item/m1"
        row[W.AUX + 1] = "https://snkrdunk.com/apparels/1/used/2"
        state, aux = W.classify(row)
        assert state == "未補充" and len(aux) == 2


class TestCostArgs:
    def test_costを手で渡せる(self):
        assert R.parse_cost_args(["--cost", "101051553=8000"]) == {"101051553": 8000.0}


class TestCostSource:
    """台帳の仕入値は「売れた時の値」。今の値を優先し、古い値では黙って戻さない。"""

    TAB = [["set_no", "title", "再仕入れ可否", "最安¥"],
           ["016/054", "Giratina", "可", "8,000"],
           ["196/SV-P", "Eevee", "可", "¥8400"],
           ["058/095", "Umbreon", "在庫なし", ""]]

    def test_最安値を今の仕入値として読む(self):
        got = R.fresh_cost_map(self.TAB)
        assert got == {"016/054": 8000.0, "196/SV-P": 8400.0}

    def test_在庫なしの行は値を作らない(self):
        assert "058/095" not in R.fresh_cost_map(self.TAB)

    def test_タイトルからcard番号を取る(self):
        o = {"Item Title": "PSA 10 Pokemon Japanese GG End #016/054 Giratina Rare 2019 Card"}
        assert R.card_no_of(o) == "016/054"
        o2 = {"Item Title": "PSA 10 Pokemon Japanese Promo #196/SV-P Eevee 2024 Card"}
        assert R.card_no_of(o2) == "196/SV-P"

    def test_番号が無ければ空(self):
        assert R.card_no_of({"Item Title": "CASIO G-Shock GA-010GGB-1A9"}) == ""


class TestNoDoubleListingOfSameCard:
    """同じカードが既に live なら補充しない (2026-08-30)。

    補充は「その行の B列が空か」だけで判断していたため、**別の行に同じカードの
    生きた出品があっても もう1本出していた** (Giratina が2本 live になった)。
    出品くん本体は同じカードの二重出品を3段で止めているが、補充は eBay を
    直接叩くのでそのどれも通らない。ここで同じ判定をする。
    """

    KEY, ITEM = 34, 1

    def _row(self, item_id, key):
        r = [""] * 40
        r[self.ITEM] = item_id
        r[self.KEY] = key
        return r

    def test_live_な出品の_KEY_を集める(self):
        sheets = [("スプシ1", [["h"], self._row("820045155453", "pokemon_tcg:SM10a-016")])]
        got = R.live_keys(sheets, {"820045155453"}, key_col=self.KEY, item_col=self.ITEM)
        assert got == {"pokemon_tcg:SM10a-016"}

    def test_live_でない出品は数えない(self):
        # B列に itemID が在っても eBay に無ければ live ではない (取下げ済など)
        sheets = [("スプシ1", [["h"], self._row("820045155453", "pokemon_tcg:SM10a-016")])]
        assert R.live_keys(sheets, set(), key_col=self.KEY, item_col=self.ITEM) == set()

    def test_KEY_が空の行は数えない(self):
        sheets = [("スプシ1", [["h"], self._row("820045155453", "")])]
        assert R.live_keys(sheets, {"820045155453"}, key_col=self.KEY, item_col=self.ITEM) == set()
