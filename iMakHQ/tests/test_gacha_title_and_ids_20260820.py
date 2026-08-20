# -*- coding: utf-8 -*-
"""ガチャ: タイトルの形 / SKU / JAN / 項目名 (2026-08-20 ユーザー指摘で全面見直し).

★何が起きていたか (実出品8件で確認):
  - タイトルが `Takara Tomy A.R.T.S ...` で始まり、先頭20字を **検索されない語**が
    占領した結果、肝心の題材が途中で切れた (`Figure Series Li` = Lizard が切れる)。
    8件中2件が**同じタイトル**になっていた
  - `C:Release Year` = eBay に存在しない項目名 (一番くじは `Year Manufactured`)
  - `C:Country of Origin` = 公式に記載が無いのに `Japan` 固定
  - SKU に楽天の**店名**が入っていた (量産品なので店が変われば別物に見える)
  - JAN(13桁) を持っているのに `Product:UPC = Does not apply` で捨てていた
"""
from __future__ import annotations

import os
import sys

HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HQ, "tools"))

import ebay_upload_csv as U                                      # noqa: E402
import gacha_to_csv as G                                         # noqa: E402


class TestTitle:
    def test_題材が先頭でメーカーは後ろ(self):
        t = G.build_title("Isekai Neko Fantasy Cat", 5, "Takara Tomy A.R.T.S", "Mini Figure")
        assert t.startswith("Isekai Neko")
        assert "Takara Tomy" in t and "A.R.T.S" not in t
        assert len(t) <= 80

    def test_八十字を超えたら後ろから削る(self):
        """題材は絶対に切らない (切れると別商品と区別が付かなくなる)."""
        t = G.build_title("Asoberu Seibutsu Figure Series Lizard Kingdom Frilled Lizard",
                          4, "Takara Tomy A.R.T.S", "Reptile Figure Collection")
        assert len(t) <= 80
        assert "Lizard Kingdom" in t          # 題材は残る
        assert t.endswith("Gashapon") or t.endswith("Japan") or "Complete Set" in t

    def test_同じ語を二回入れない(self):
        t = G.build_title("Insect Forest Beetle", 4, "Takara Tomy", "Beetle Figure")
        assert t.lower().count("beetle") == 1

    def test_種類数が必ず入る(self):
        assert "Complete Set 7" in G.build_title("Imuraya Sweets", 7, "Takara Tomy")


class TestSku:
    def test_楽天は店名を入れず商品IDだけ(self):
        assert G.supply_sku("https://item.rakuten.co.jp/auc-yuyou/g22062cs02/") == "g22062cs02"

    def test_メルカリは今までどおり(self):
        assert G.supply_sku("https://jp.mercari.com/item/m35315305722") == "m35315305722"

    def test_読めないURLは空(self):
        """推測でSKUを作らない (間違ったSKUは仕入元を引けなくする)."""
        assert G.supply_sku("https://example.com/x") == ""


class TestEan:
    def test_JANがeBayに送られる(self):
        x = U.build_item_xml({"*Title": "t", "Product:EAN": "4549660717034"})
        assert "<EAN>4549660717034</EAN>" in x
        # eBay のカタログにタイトル/画像を上書きさせない
        assert "<IncludeeBayProductDetails>false</IncludeeBayProductDetails>" in x

    def test_無ければ何も送らない(self):
        assert "ProductListingDetails" not in U.build_item_xml({"*Title": "t"})
