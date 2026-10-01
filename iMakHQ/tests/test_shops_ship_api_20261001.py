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


def test_api_detail_maps_item_and_shops(monkeypatch):
    """一番くじの詳細を API で読む (2026-10-02)。控えと同じ形・同じ言葉で返す。"""
    import asyncio
    import types
    NS = types.SimpleNamespace

    class FakeApi:
        async def item(self, i):
            return NS(item_condition=NS(name="新品、未使用"), shipping_payer=NS(code="seller"),
                      seller=NS(name="柴", num_ratings=277, star_rating_score="5"),
                      shipping_duration=NS(name="1~2日で発送"), status="on_sale", auction_info=None)

        async def product(self, p):
            pd = NS(condition=NS(display_name="目立った傷や汚れなし"), shipping_payer=NS(code="BUYER"),
                    variants=[NS(quantity="1")], shipping_duration=NS(display_name="4〜7日で発送"))
            return NS(product_detail=pd)

    monkeypatch.setattr(mp, "_API_ONE", {"api": FakeApi(), "loop": asyncio.new_event_loop()})
    monkeypatch.setattr(mp, "_API_SLEEP", 0)
    a = mp.api_detail("https://jp.mercari.com/item/m123")
    assert a == {"cond": "新品、未使用", "ship": "送料込み", "reviews": 277, "buyable": True,
                 "seller": "柴", "star": 5.0, "ship_days": "1~2日で発送"}
    s = mp.api_detail("https://jp.mercari.com/shops/product/ABC")
    assert s["ship"] == "送料別" and s["buyable"] is True and s["reviews"] is None
    assert mp.api_detail("https://snkrdunk.com/x") is None
