"""メルカリ Shops 候補画像を large に上げる (2026-07-28).

個人出品は orig 画像を組めるが、**Shops だけ検索結果のサムネのまま**目視に出ていた。
実測 (2026-07-28): Shops 商品ページの og:image は
  https://assets.mercari-shops-static.com/-/large/plain/<id>.jpg@jpg
= PSA cert 画像の /small/→/large/ と同じ形。size セグメントの差し替えで見比べ精度を上げる。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

from psa_resource_html import shops_image_large  # noqa: E402

HOST = "https://assets.mercari-shops-static.com/-/"


def test_thumbnail_size_is_upgraded():
    assert shops_image_large(HOST + "240x240/plain/ABC.jpg@webp") == HOST + "large/plain/ABC.jpg@webp"


def test_already_large_is_unchanged():
    u = HOST + "large/plain/ABC.jpg@jpg"
    assert shops_image_large(u) == u


def test_only_first_size_segment_is_replaced():
    """plain 以降のパスに似た文字列があっても壊さない。"""
    got = shops_image_large(HOST + "96x96/plain/240x240/ABC.jpg")
    assert got == HOST + "large/plain/240x240/ABC.jpg"


def test_non_shops_urls_are_untouched():
    for u in ("https://static.mercdn.net/item/detail/orig/photos/m123456789_1.jpg",
              "https://i.ebayimg.com/00/s/MTA4MFgxMDgw/z/x/$_57.PNG",
              "https://cdn.snkrdunk.com/upload/a.webp",
              ""):
        assert shops_image_large(u) == u


def test_none_is_passed_through():
    """呼び手が無条件に通せること (None を壊さない)。"""
    assert shops_image_large(None) is None
