"""tests/test_workman_extract - Workman 公式 商品ページ JSON-LD 抽出のオフラインテスト.

実機 (workman.jp) 観測サンプルを HTML 文字列にした fixture で extract / parse ロジックを検証。
Selenium / requests は使わない pure offline test。
"""
from __future__ import annotations

import pytest

from scrapers.workman_official import (
    extract_jsonld_product,
    normalize_workman_url,
    parse_workman_mpn,
    parse_workman_product_html,
)


pytestmark = pytest.mark.offline


# 実機 (https://workman.jp/shop/g/g2300011882014/) 観測サンプル
SAMPLE_HTML_BASIC = '''
<html><head><title>11882 ゼロステージアイストライブレギンス | ワークマン公式オンラインストア</title>
<script type="application/ld+json">
{
   "@context":"http:\\/\\/schema.org\\/",
   "@type":"Product",
   "name":"ゼロステージアイストライブレギンス",
   "image":"https:\\u002f\\u002fworkman.jp\\u002fimg\\u002fgoods\\u002fS\\u002f11882_t1.jpg",
   "description":"",
   "color":"ブラック",
   "mpn":"2300011882014",
   "releaseDate":"2026/03/04",
   "brand": {
      "@type": "Thing",
      "name": "その他ブランド"
   },
   "offers":{
      "@type":"Offer",
      "price":2500,
      "priceCurrency":"JPY",
      "availability":"http:\\/\\/schema.org\\/InStock"
   }
}
</script></head><body></body></html>
'''

SAMPLE_HTML_OUT_OF_STOCK = '''
<script type="application/ld+json">
{
   "@type":"Product",
   "name":"テスト商品",
   "image":"https://workman.jp/img/goods/S/99999_t1.jpg",
   "color":"ネイビー",
   "mpn":"2300099999014",
   "offers":{
      "price":1980,
      "priceCurrency":"JPY",
      "availability":"http://schema.org/OutOfStock"
   }
}
</script>
'''


# --------------------------------------------------------------------------
# parse_workman_mpn
# --------------------------------------------------------------------------
class TestParseWorkmanMpn:
    def test_basic_url(self):
        assert parse_workman_mpn("https://workman.jp/shop/g/g2300011882014/") == "2300011882014"

    def test_url_without_trailing_slash(self):
        assert parse_workman_mpn("https://workman.jp/shop/g/g2300011882014") == "2300011882014"

    def test_url_with_query(self):
        assert parse_workman_mpn("https://workman.jp/shop/g/g2300011882014/?ref=foo") == "2300011882014"

    def test_invalid_url(self):
        assert parse_workman_mpn("https://example.com/foo") is None
        assert parse_workman_mpn("https://workman.jp/shop/e/ezero-st/") is None

    def test_empty(self):
        assert parse_workman_mpn("") is None
        assert parse_workman_mpn(None) is None  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# normalize_workman_url
# --------------------------------------------------------------------------
class TestNormalizeWorkmanUrl:
    def test_from_full_url(self):
        assert normalize_workman_url(
            "https://workman.jp/shop/g/g2300011882014/?ref=foo"
        ) == "https://workman.jp/shop/g/g2300011882014/"

    def test_from_mpn_only(self):
        assert normalize_workman_url("2300011882014") == "https://workman.jp/shop/g/g2300011882014/"

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            normalize_workman_url("https://example.com/foo")
        with pytest.raises(ValueError):
            normalize_workman_url("")


# --------------------------------------------------------------------------
# extract_jsonld_product
# --------------------------------------------------------------------------
class TestExtractJsonldProduct:
    def test_basic_extraction(self):
        data = extract_jsonld_product(SAMPLE_HTML_BASIC)
        assert data is not None
        assert data.get("@type") == "Product"
        assert data.get("name") == "ゼロステージアイストライブレギンス"
        assert data.get("mpn") == "2300011882014"

    def test_returns_none_for_html_without_jsonld(self):
        assert extract_jsonld_product("<html><body>No JSON-LD here</body></html>") is None

    def test_returns_none_for_invalid_json(self):
        html = '<script type="application/ld+json">{ invalid json }</script>'
        assert extract_jsonld_product(html) is None

    def test_handles_array_jsonld(self):
        html = '''
        <script type="application/ld+json">
        [
          {"@type": "BreadcrumbList", "name": "breadcrumb"},
          {"@type": "Product", "name": "テスト", "mpn": "1234567890123"}
        ]
        </script>
        '''
        data = extract_jsonld_product(html)
        assert data is not None
        assert data.get("@type") == "Product"
        assert data.get("name") == "テスト"

    def test_empty_html(self):
        assert extract_jsonld_product("") is None


# --------------------------------------------------------------------------
# parse_workman_product_html
# --------------------------------------------------------------------------
class TestParseWorkmanProductHtml:
    def test_basic_parse(self):
        data = parse_workman_product_html(
            SAMPLE_HTML_BASIC,
            url="https://workman.jp/shop/g/g2300011882014/",
        )
        assert data is not None
        assert data["mpn"] == "2300011882014"
        assert data["title"] == "ゼロステージアイストライブレギンス"
        assert data["color"] == "ブラック"
        assert data["price_jpy"] == 2500
        assert data["in_stock"] is True
        assert data["status"] == "ON_SALE"
        assert data["size"] == ""  # Workman は 1 URL = 1 SKU、size は別 mpn で展開
        assert data["brand"] == "その他ブランド"
        assert data["condition"] == "New"
        assert data["release_date"] == "2026/03/04"

    def test_image_urls_include_thumb_and_hires(self):
        data = parse_workman_product_html(SAMPLE_HTML_BASIC)
        # 元 thumb + 高解像度版 (置換可能なら) を含む
        assert len(data["image_urls"]) >= 1
        assert data["image_urls"][0].endswith("_t1.jpg")
        # 高解像度版が含まれる場合 _l1.jpg に置換されている
        if len(data["image_urls"]) > 1:
            assert any(u.endswith("_l1.jpg") for u in data["image_urls"])

    def test_out_of_stock(self):
        data = parse_workman_product_html(SAMPLE_HTML_OUT_OF_STOCK)
        assert data["in_stock"] is False
        assert data["status"] == "OUT_OF_STOCK"
        assert data["color"] == "ネイビー"

    def test_returns_none_when_no_jsonld(self):
        assert parse_workman_product_html("<html><body>nothing here</body></html>") is None

    def test_url_inferred_from_mpn_when_arg_empty(self):
        data = parse_workman_product_html(SAMPLE_HTML_BASIC, url="")
        # JSON-LD の isSimilarTo.url を見るか、mpn から URL 構築するか
        # 本ケースは isSimilarTo がないので mpn から構築される
        assert "2300011882014" in data["url"]
        assert "workman.jp/shop/g" in data["url"]

    def test_brand_when_dict_format(self):
        # brand が dict 形式
        data = parse_workman_product_html(SAMPLE_HTML_BASIC)
        assert data["brand"] == "その他ブランド"

    def test_color_is_katakana(self):
        # Workman JSON-LD color は カタカナで取得される (Vision AI 不要の利点)
        data = parse_workman_product_html(SAMPLE_HTML_BASIC)
        assert data["color"] == "ブラック"
        # 漢字 reject ルール (Phase 1d-2 で全 supplier 共通) に違反しない
        # → harvest 時の S 列に直接書込可能


# --------------------------------------------------------------------------
# fail-closed 確認
# --------------------------------------------------------------------------
class TestFailClosed:
    def test_missing_price_returns_none(self):
        html = '''
        <script type="application/ld+json">
        {"@type": "Product", "name": "test", "mpn": "1234567890123", "color": "ブラック"}
        </script>
        '''
        data = parse_workman_product_html(html)
        assert data is not None
        assert data["price_jpy"] is None

    def test_missing_availability_returns_unknown_status(self):
        html = '''
        <script type="application/ld+json">
        {"@type": "Product", "name": "test", "mpn": "1234567890123", "offers": {"price": 100}}
        </script>
        '''
        data = parse_workman_product_html(html)
        assert data["in_stock"] is None
        assert data["status"] == "UNKNOWN"

    def test_missing_color_returns_empty_string(self):
        html = '''
        <script type="application/ld+json">
        {"@type": "Product", "name": "test", "mpn": "1234567890123"}
        </script>
        '''
        data = parse_workman_product_html(html)
        assert data["color"] == ""
