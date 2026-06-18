# -*- coding: utf-8 -*-
"""RESTOCK確証の画像解決 回帰テスト (2026-06-19)。

真因: _resolve_image_url(mercari出品ページ→CDN直画像 / snkrdunk→og:image)が
定義only・/img プロキシに未配線だった。candidate の出品ページURLをそのまま画像として
掴み、全候補が「画像なし」になっていた。修正: do_GET の /img で _fetch_image 前に
_resolve_image_url をかます。ここでは解決関数のルーティングを固定する。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

import psa_resource_confirm as prc


def test_mercari_item_resolves_to_static_cdn():
    """mercari item (m<id>) ページURL → 静的CDN直画像(ページ取得不要)。"""
    u = "https://jp.mercari.com/item/m12345678901"
    got = prc._resolve_image_url(u)
    assert got == "https://static.mercdn.net/item/detail/orig/photos/m12345678901_1.jpg"


def test_direct_mercdn_image_passthrough():
    """既に mercdn の直画像URLはそのまま(二重解決しない)。"""
    u = "https://static.mercdn.net/item/detail/orig/photos/m12345678901_1.jpg"
    assert prc._resolve_image_url(u) == u


def test_catalog_or_ebay_image_passthrough():
    """catalog/eBay の直画像URLはそのまま。"""
    u = "https://i.ebayimg.com/00/s/abc/z/xyz/$_57.JPG"
    assert prc._resolve_image_url(u) == u


def test_snkrdunk_page_uses_og_image(monkeypatch):
    """snkrdunk 商品ページ → og:image 解決(ネットワークは monkeypatch)。"""
    monkeypatch.setattr(prc, "_fetch_og_image", lambda url: "https://cdn.snkrdunk.com/og/abc.jpg")
    u = "https://snkrdunk.com/trading-cards/12345"
    assert prc._resolve_image_url(u) == "https://cdn.snkrdunk.com/og/abc.jpg"


def test_mercari_shops_no_itemid_uses_og(monkeypatch):
    """mercari shops 等 m<id> が無いページ → og:image。"""
    monkeypatch.setattr(prc, "_fetch_og_image", lambda url: "https://cdn.mercari/og.jpg")
    u = "https://jp.mercari.com/shops/product/abcXYZ"
    assert prc._resolve_image_url(u) == "https://cdn.mercari/og.jpg"


def test_empty_url():
    assert prc._resolve_image_url("") == ""
    assert prc._resolve_image_url(None) == ""
