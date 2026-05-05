"""tests/test_mercari_shops_likes - Mercari Shops いいね URL 抽出ロジック単体テスト.

Selenium / 認証は使わず、HTML 文字列ベースで extract / parse のみ検証する offline テスト。
"""
from __future__ import annotations

import pytest

from scrapers.mercari_shops_likes import (
    extract_shops_likes_from_html,
    parse_shop_product_id,
)


pytestmark = pytest.mark.offline


# --------------------------------------------------------------------------
# parse_shop_product_id
# --------------------------------------------------------------------------
class TestParseShopProductId:
    def test_basic_url(self):
        assert parse_shop_product_id(
            "https://jp.mercari.com/shops/product/2JNysv3RcsZP37Dt8Zoaof"
        ) == "2JNysv3RcsZP37Dt8Zoaof"

    def test_relative_url(self):
        assert parse_shop_product_id("/shops/product/2JPtVUPYKD3r6PRrGuLraZ") == "2JPtVUPYKD3r6PRrGuLraZ"

    def test_with_query(self):
        assert parse_shop_product_id(
            "https://jp.mercari.com/shops/product/2JQXtW34QZEgJN5uRMi89D?ref=likes"
        ) == "2JQXtW34QZEgJN5uRMi89D"

    def test_real_world_slugs(self):
        # Phase 1b 着手時にユーザーから提供された実 URL
        cases = [
            ("https://jp.mercari.com/shops/product/2JNysv3RcsZP37Dt8Zoaof", "2JNysv3RcsZP37Dt8Zoaof"),
            ("https://jp.mercari.com/shops/product/2JPtVUPYKD3r6PRrGuLraZ", "2JPtVUPYKD3r6PRrGuLraZ"),
            ("https://jp.mercari.com/shops/product/2JQXtW34QZEgJN5uRMi89D", "2JQXtW34QZEgJN5uRMi89D"),
        ]
        for url, expected in cases:
            assert parse_shop_product_id(url) == expected

    def test_regular_mercari_url_returns_none(self):
        # 通常 Mercari /item/m... は対象外
        assert parse_shop_product_id("https://jp.mercari.com/item/m12345678901") is None

    def test_empty(self):
        assert parse_shop_product_id("") is None
        assert parse_shop_product_id(None) is None  # type: ignore[arg-type]

    def test_garbage(self):
        assert parse_shop_product_id("https://example.com/foo/bar") is None


# --------------------------------------------------------------------------
# extract_shops_likes_from_html
# --------------------------------------------------------------------------
def _build_shops_likes_html(slugs: list[str], use_testid: bool = True) -> str:
    """ダミー Shops いいねページ HTML を生成 (data-testid 有/無 切替)."""
    anchors = []
    for slug in slugs:
        if use_testid:
            anchors.append(
                f'<a data-testid="shops-liked-item" href="/shops/product/{slug}">name</a>'
            )
        else:
            anchors.append(f'<a href="/shops/product/{slug}">name</a>')
    return f"<html><body>{''.join(anchors)}</body></html>"


class TestExtractShopsLikesFromHtml:
    def test_basic_extraction(self):
        slugs = [
            "2JNysv3RcsZP37Dt8Zoaof",
            "2JPtVUPYKD3r6PRrGuLraZ",
            "2JQXtW34QZEgJN5uRMi89D",
        ]
        html = _build_shops_likes_html(slugs)
        items = extract_shops_likes_from_html(html)
        assert [it["shop_product_id"] for it in items] == slugs
        # URL が絶対化されている
        assert all(it["url"].startswith("https://jp.mercari.com/shops/product/") for it in items)

    def test_dedupes_same_slug(self):
        slugs = ["2JNysv3RcsZP37Dt8Zoaof", "2JPtVUPYKD3r6PRrGuLraZ", "2JNysv3RcsZP37Dt8Zoaof"]
        html = _build_shops_likes_html(slugs)
        items = extract_shops_likes_from_html(html)
        ids = [it["shop_product_id"] for it in items]
        assert ids == ["2JNysv3RcsZP37Dt8Zoaof", "2JPtVUPYKD3r6PRrGuLraZ"]

    def test_fallback_when_testid_missing(self):
        # data-testid が外れた場合、a[href*='/shops/product/'] フォールバックで拾える
        html = _build_shops_likes_html(["2JABCDEFG12345678901"], use_testid=False)
        items = extract_shops_likes_from_html(html)
        assert [it["shop_product_id"] for it in items] == ["2JABCDEFG12345678901"]

    def test_ignores_regular_mercari_anchors(self):
        # 通常 Mercari /item/m... は Shops 抽出に含まれない
        html = '''
        <html><body>
          <a data-testid="mercari-liked-item" href="/item/m11111111111">通常品</a>
          <a data-testid="shops-liked-item" href="/shops/product/2JNysv3RcsZP37Dt8Zoaof">shop</a>
        </body></html>
        '''
        items = extract_shops_likes_from_html(html)
        assert [it["shop_product_id"] for it in items] == ["2JNysv3RcsZP37Dt8Zoaof"]

    def test_ignores_non_product_anchors(self):
        html = '''
        <html><body>
          <a data-testid="shops-liked-item" href="/shops/product/2JABCDEFG12345678901">x</a>
          <a href="/category/foo">x</a>
          <a href="https://help.mercari.com/">x</a>
        </body></html>
        '''
        items = extract_shops_likes_from_html(html)
        assert [it["shop_product_id"] for it in items] == ["2JABCDEFG12345678901"]

    def test_absolute_url_passes_through(self):
        html = (
            '<a data-testid="shops-liked-item" '
            'href="https://jp.mercari.com/shops/product/2JABCDEFG12345678901?ref=likes">x</a>'
        )
        items = extract_shops_likes_from_html(html)
        assert items[0]["url"] == "https://jp.mercari.com/shops/product/2JABCDEFG12345678901?ref=likes"
        assert items[0]["shop_product_id"] == "2JABCDEFG12345678901"

    def test_empty_html(self):
        assert extract_shops_likes_from_html("<html><body></body></html>") == []
        assert extract_shops_likes_from_html("") == []

    def test_real_world_dom_structure(self):
        # 2026-05-06 DOM 確認で観測された実 HTML 構造を再現
        html = '''
        <html><body>
        <div class="group">
          <a target="_blank" rel="noopener noreferrer" data-location="likes:item_row"
             data-testid="shops-liked-item"
             href="/shops/product/2JNysv3RcsZP37Dt8Zoaof"
             aria-labelledby="_r_4_">
            <span><picture><img height="64" width="64"></picture></span>
          </a>
        </div>
        </body></html>
        '''
        items = extract_shops_likes_from_html(html)
        assert len(items) == 1
        assert items[0]["shop_product_id"] == "2JNysv3RcsZP37Dt8Zoaof"
        assert items[0]["url"] == "https://jp.mercari.com/shops/product/2JNysv3RcsZP37Dt8Zoaof"
