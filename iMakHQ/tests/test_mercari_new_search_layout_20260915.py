# -*- coding: utf-8 -*-
"""メルカリ検索結果の新しいページの形も読む (2026-09-15)。

9/14 夜から UT の補URL検索 (一時プロファイルの headless) だけ **拾えた0** が続いた。
実機のページ (ドラゴンボール DAIMA UT Tシャツ) は 42 cell 中 20件が表示されていたが、
cell に itemtype も aria-label="<名前>の画像 <価格>円" も無くなり、読み取りが全件0だった。
新しい形: href="/item/m…" / <p data-testid="thumbnail-item-name">名前</p> /
<span data-testid="item-tile-price"><span>¥</span><span>680</span></span>。
PSA の夜間検索 (別のプロファイル) は旧形のまま取れているので、**両方読む**。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import mercari_psa_resource as mp  # noqa: E402


def _cell(href, name, price, extra=""):
    # 実機の cell から class を削っただけの形
    return ('<li data-testid="item-cell"><div><div><div><a href="%s" '
            'data-location="search_result:lowest_price:body:item_list:item_thumbnail" '
            'data-testid="thumbnail-link" target="_blank" aria-labelledby="_r_a_ _r_8_ _r_9_">'
            '<span><picture><img alt="%sのサムネイル" src="https://static.mercdn.net/thumb/item/webp/m1_1.jpg">'
            '</picture><div><span data-testid="item-tile-price" id="_r_9_"><span>'
            '<span class="a">¥</span><span class="b">%s</span></span></span></div></span>'
            '<div id="_r_a_"><div><p data-testid="thumbnail-item-name" class="c">%s</p></div></div>%s'
            '</a></div></div></div></li>') % (href, name, price, name, extra)


def test_reads_name_price_href_from_new_layout():
    src = _cell("/item/m54064219278", "UNIQLO UT DRAGON BALL DAIMA Tシャツ　Mサイズ", "680")
    assert mp.parse_mercari_items(src) == [{
        "type": "ITEM_TYPE_MERCARI", "name": "UNIQLO UT DRAGON BALL DAIMA Tシャツ　Mサイズ",
        "price": 680, "href": "https://jp.mercari.com/item/m54064219278"}]


def test_comma_price_shops_and_html_entities():
    src = (_cell("/item/m1", "A &amp; B Tシャツ", "2,077")
           + _cell("/shops/product/AbC123", "ショップの Tシャツ", "1,500"))
    got = mp.parse_mercari_items(src)
    assert [(g["type"], g["name"], g["price"]) for g in got] == [
        ("ITEM_TYPE_MERCARI", "A & B Tシャツ", 2077), ("ITEM_TYPE_BEYOND", "ショップの Tシャツ", 1500)]
    assert got[1]["href"] == "https://jp.mercari.com/shops/product/AbC123"


def test_placeholder_cells_and_auction_markers_are_skipped():
    src = ('<li data-testid="item-cell"><div></div></li>'                       # まだ描画されていない枠
           + _cell("/item/m2", "Tシャツ", "900", extra="<span>現在価格</span>")    # オークション
           + _cell("/item/m3", "Tシャツ L", "1,000"))
    assert [g["href"][-2:] for g in mp.parse_mercari_items(src)] == ["m3"]


def test_page_tail_text_does_not_poison_the_last_cell():
    """最後の cell の後ろにある文言データの「オークション」で、最後の商品を落とさない。"""
    src = _cell("/item/m4", "Tシャツ XL", "1,200") + '<script>{"auction":{"title":"参加中のオークション"}}</script>'
    assert [g["price"] for g in mp.parse_mercari_items(src)] == [1200]


def test_lots_are_still_dropped_in_new_layout():
    name = "UT Tシャツ 3枚セット まとめ売り"
    assert mp._is_lot(name)
    assert mp.parse_mercari_items(_cell("/item/m5", name, "3,000")) == []


def test_old_layout_still_parsed():
    old = ('data-testid="item-cell" class="x"><a href="/item/m9"><div aria-label="Tシャツの画像 1,234円" '
           'itemtype="ITEM_TYPE_MERCARI"></div></a>')
    assert mp.parse_mercari_items(old) == [{"type": "ITEM_TYPE_MERCARI", "name": "Tシャツ",
                                            "price": 1234, "href": "https://jp.mercari.com/item/m9"}]


def test_auction_price_now_is_skipped():
    """新しい形のオークションは価格が「現在 ¥300」(実機 9/15 PSA10 検索で44件)。確定価格ではないので拾わない。"""
    auction = _cell("/item/m89712062696", "ピカチュウV RR 25th PSA10", "300").replace(
        '<span class="a">¥</span>', '<span class="a">現在 ¥</span>')
    assert mp.parse_mercari_items(auction) == []
    assert mp._parse_new_layout_cell(auction.replace("現在 ", "")) is not None
