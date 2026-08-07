#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""demand_winners の facet 抽出 (size_of / color_of) 回帰テスト。

過去バグ (2026-06-04 監査で発覚):
  1. size_of が "US L (JP XL)" で JP サイズ(XL)を拾っていた → eBay バイヤーが
     検索する US サイズに統一すべき (UT 170件中 75件で取り違え=「XL圧倒」artifact)。
  2. color_of が "Blue Lock" 等フランチャイズ名の色語を商品色と誤認していた
     (例: Blue Lock UT Gray → "Blue" と誤判定。16件+)。
"""
import importlib.util
import os

import pytest

_DW = os.path.join(os.path.dirname(__file__), "..", "tools", "demand_winners.py")
_spec = importlib.util.spec_from_file_location("demand_winners", _DW)
dw = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dw)


@pytest.mark.parametrize("title,expected", [
    # US 優先: "US L (JP XL)" は L (JP の XL を拾わない) ← バグ本体
    ("Uniqlo UT Jujutsu Kaisen Yuji Itadori T-Shirt US L (JP XL) Navy", "L"),
    ("UNIQLO UT One Piece Straw Hat Crew T-Shirt US L (JP XL) White", "L"),
    ("Uniqlo UT Kenshi Yonezu T-shirt Blue US Size L (JP XL) New", "L"),
    # US XL (JP XXL) は XL
    ("UNIQLO UT Dragon Ball DAIMA Goku T-Shirt Navy US XL (JP XXL) NWT", "XL"),
    ("UNIQLO UT Dragon Ball Goku T-Shirt Beige US 2XL (JP 3XL) NWT", "2XL"),
    ("Montbell Thunder Pass Jacket 1128344 US M (JP L) Flame Yellow", "M"),
    # US 表記なし → 単独サイズ語そのまま
    ("Montbell GORE-TEX Red Nylon Jacket XL Waterproof Outdoor Shell", "XL"),
    ("YOSHIDA PORTER Tanker Shoulder Bag XL Green Sage Nylon", "XL"),
    # サイズ無し → None
    ("CASIO G-SHOCK GA-2100-1A1JF Men's Digital Watch Black", None),
])
def test_size_of_prefers_us(title, expected):
    assert dw.size_of(title) == expected


@pytest.mark.parametrize("title,expected", [
    # フランチャイズ名の色語は無視し、実際の商品色を返す ← バグ本体
    ("Uniqlo Blue Lock UT Graphic T-Shirt Gray Seishiro Nagi Anime", "Gray"),
    ("Uniqlo Blue Lock UT Graphic T-Shirt White Isagi Nagi Anime", "White"),
    ("Uniqlo Blue Lock UT Graphic T-Shirt Black Isagi Yoichi Anime", "Black"),
    ("One Piece THEORAMA SOUL Shanks Figure Red Hair Diorama Black", "Black"),
    # 実際に青いシャツは Blue で正しい (Blue Lock 除去後も Blue が残る)
    ("Uniqlo Blue Lock UT Graphic T-Shirt Blue Michael Kaiser Anime", "Blue"),
    # 通常ケース
    ("Montbell GORE-TEX Red Nylon Jacket XL Outdoor Shell", "Red"),
    ("montbell Light Shell Parka Gray US M (JP L) Pre-owned", "Gray"),
])
def test_color_of_ignores_franchise(title, expected):
    assert dw.color_of(title) == expected


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
