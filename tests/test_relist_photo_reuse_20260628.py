# -*- coding: utf-8 -*-
"""取下再出品② 画像流用 回帰テスト (2026-06-28)。

バグ: relist で画像をソース(mercari/1kuji.com)から取り直し → ichibankuji は 1kuji.com の
汎用OG画像(ogp.jpg)混入 or 画像取得失敗で行スキップ → 取下げたのに再出品できない(fail-OPEN)。
修正: relist は取下げた元eBay listing の画像を流用(fetch_listing_images)。0件時のみソースfallback。
(pre-commit が collect する tests/ に配置。重い mercari モジュールは import せず純関数を検証)
"""
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "iMakeBayAPI")))

import ebay_getitem_images as g  # noqa: E402


def test_relist_uses_ebay_images_over_source():
    """relist時: 元eBay画像が在ればソース(1kuji.com/ogp.jpg)でなくそれを使う。"""
    ebay = ["https://i.ebayimg.com/a.jpg", "https://i.ebayimg.com/b.jpg"]
    urls, note = g.relist_photo_source(
        True, "358376729586", "https://1kuji.com/ogp.jpg", fetch_fn=lambda iid: ebay)
    assert urls == "https://i.ebayimg.com/a.jpg|https://i.ebayimg.com/b.jpg"
    assert "1kuji.com" not in urls
    assert "流用" in note


def test_relist_fallback_to_source_when_no_ebay_images():
    """元eBay画像0(ended>90日/API失敗)→ ソースに fallback(画像消失で誤出品しない)。"""
    urls, note = g.relist_photo_source(
        True, "999", "https://src/img.jpg", fetch_fn=lambda iid: [])
    assert urls == "https://src/img.jpg"
    assert "fallback" in note or "ソース" in note


def test_relist_fetch_exception_falls_back():
    urls, _ = g.relist_photo_source(
        True, "999", "src.jpg", fetch_fn=lambda iid: (_ for _ in ()).throw(RuntimeError("net")))
    assert urls == "src.jpg"


def test_non_relist_keeps_source_untouched():
    """通常出品(relist_mode=False)は source そのまま・fetch 呼ばない。"""
    called = []
    urls, note = g.relist_photo_source(
        False, "x", "src.jpg", fetch_fn=lambda iid: called.append(iid) or ["e.jpg"])
    assert urls == "src.jpg" and note == "" and called == []


def test_fetch_listing_condition_empty_is_none():
    """空itemIDは None(契約)。relist condition 継承の安全側。"""
    assert g.fetch_listing_condition("") is None
