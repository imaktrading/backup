"""メルカリ Shops の送料・在庫 (2026-10-01)。

- Shops も API (shops/products) で送料の負担と在庫数が取れる → Chrome を開かない
- 詳細ページの読み方が「送料別(購入者負担)」を知らず、後方の翻訳文字列「送料込み(出品者負担)」を
  拾って、送料別の Shops を送料込みと判定していた (実測 2JUsfu…: 画面は送料別 ¥200)
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import ichibankuji_restock as ir  # noqa: E402
import mercari_psa_resource as mp  # noqa: E402


def test_api_shops_verdict():
    assert mp.api_shops_verdict("SELLER", ["5"]) == (True, "送料込み", True)
    assert mp.api_shops_verdict("BUYER", ["5"]) == (False, "着払い", True)      # 送料別 = 外す
    assert mp.api_shops_verdict("SELLER", ["0", "0"]) == (False, "送料込み", False)  # 在庫なし
    assert mp.api_shops_verdict("SELLER", ["x"]) == (False, "送料込み", False)    # 読めない = 0
    assert mp.api_shops_verdict(None, ["1"]) == (False, "", True)


# 実ページの並び: 商品の欄 → … → ページ後方に翻訳用の文字列 (配送料の負担 … 送料込み(出品者負担))
_PAGE_SHOPS_BUYER = ('<div>商品の状態</div><span>目立った傷や汚れなし</span>'
                     '<div>配送料の負担</div><span>送料別(購入者負担)</span>'
                     + 'x' * 500 +
                     '"shippingPayer":"配送料の負担","seller":"送料込み(出品者負担)"')
_PAGE_SHOPS_SELLER = ('<div>商品の状態</div><span>新品、未使用</span>'
                      '<div>配送料の負担</div><span>送料込み(出品者負担)</span>')


def test_parse_cond_ship_reads_shops_buyer_pays():
    assert mp._parse_cond_ship(_PAGE_SHOPS_BUYER)[1] == "送料別"
    assert mp._parse_cond_ship(_PAGE_SHOPS_SELLER)[1] == "送料込み"
    assert ir._parse_cond_ship(_PAGE_SHOPS_BUYER)[1] == "送料別"
    assert ir._parse_cond_ship(_PAGE_SHOPS_SELLER)[1] == "送料込み"
    # 送料別は候補に入らない
    assert mp.candidate_passes_filter("", "送料別", None, True) is False
