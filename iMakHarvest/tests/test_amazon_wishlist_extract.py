"""tests/test_amazon_wishlist_extract - extract_wishlist_items_from_html /
parse_asin / parse_wishlist_id / normalize_wishlist_url の単体テスト.

Selenium / 認証は使わず、文字列ベースで HTML 抽出ロジックのみ検証する offline テスト。
"""
from __future__ import annotations

import pytest

from scrapers.amazon_wishlist import (
    extract_wishlist_items_from_html,
    normalize_wishlist_url,
    parse_asin,
    parse_wishlist_id,
)


pytestmark = pytest.mark.offline


# --------------------------------------------------------------------------
# parse_asin
# --------------------------------------------------------------------------
class TestParseAsin:
    def test_dp_url(self):
        assert parse_asin("https://www.amazon.co.jp/dp/B08N5WRWNW") == "B08N5WRWNW"

    def test_gp_product_url(self):
        assert parse_asin("https://www.amazon.co.jp/gp/product/B08N5WRWNW") == "B08N5WRWNW"

    def test_gp_aw_d_url(self):
        # mobile path
        assert parse_asin("https://www.amazon.co.jp/gp/aw/d/B08N5WRWNW") == "B08N5WRWNW"

    def test_dp_with_trailing_path(self):
        # /dp/<ASIN>/ref=... なパターン
        assert parse_asin(
            "https://www.amazon.co.jp/dp/B08N5WRWNW/ref=cm_sw_r_other_apa_xx"
        ) == "B08N5WRWNW"

    def test_dp_with_query(self):
        assert parse_asin("https://www.amazon.co.jp/dp/B08N5WRWNW?th=1") == "B08N5WRWNW"

    def test_lowercase_input_returns_uppercase(self):
        assert parse_asin("https://www.amazon.co.jp/dp/b08n5wrwnw") == "B08N5WRWNW"

    def test_empty(self):
        assert parse_asin("") is None
        assert parse_asin(None) is None  # type: ignore[arg-type]

    def test_garbage(self):
        assert parse_asin("https://example.com/foo/bar") is None

    def test_mercari_url_returns_none(self):
        assert parse_asin("https://jp.mercari.com/item/m12345678901") is None

    def test_short_id_does_not_match(self):
        # ASIN は 10 文字必須
        assert parse_asin("https://www.amazon.co.jp/dp/B08N5WRWN") is None


# --------------------------------------------------------------------------
# parse_wishlist_id / normalize_wishlist_url
# --------------------------------------------------------------------------
class TestParseWishlistId:
    def test_basic(self):
        assert parse_wishlist_id(
            "https://www.amazon.co.jp/hz/wishlist/ls/10T7E6IA1HL9"
        ) == "10T7E6IA1HL9"

    def test_with_ref_suffix(self):
        # ユーザーが提示した実 URL 形式
        assert parse_wishlist_id(
            "https://www.amazon.co.jp/hz/wishlist/ls/10T7E6IA1HL9/ref=nav_wishlist_lists_1"
        ) == "10T7E6IA1HL9"

    def test_with_query(self):
        assert parse_wishlist_id(
            "https://www.amazon.co.jp/hz/wishlist/ls/10T7E6IA1HL9?ref_=foo"
        ) == "10T7E6IA1HL9"

    def test_empty(self):
        assert parse_wishlist_id("") is None

    def test_invalid(self):
        assert parse_wishlist_id("https://example.com/foo") is None


class TestNormalizeWishlistUrl:
    def test_strips_ref_suffix(self):
        normalized = normalize_wishlist_url(
            "https://www.amazon.co.jp/hz/wishlist/ls/10T7E6IA1HL9/ref=nav_wishlist_lists_1"
        )
        assert normalized == "https://www.amazon.co.jp/hz/wishlist/ls/10T7E6IA1HL9"

    def test_already_normalized(self):
        url = "https://www.amazon.co.jp/hz/wishlist/ls/10T7E6IA1HL9"
        assert normalize_wishlist_url(url) == url

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            normalize_wishlist_url("https://example.com/foo")

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            normalize_wishlist_url("")


# --------------------------------------------------------------------------
# extract_wishlist_items_from_html
# --------------------------------------------------------------------------
def _build_wishlist_html(items: list[tuple[str, str]], use_data_id: bool = True) -> str:
    """ダミーウィッシュリスト HTML を生成.

    items: [(asin, title), ...]
    use_data_id=True: 標準構造 (li[data-id="ASIN"])
    use_data_id=False: フォールバック (a[href*='/dp/'] のみ)
    """
    li_tags = []
    for asin, title in items:
        if use_data_id:
            li_tags.append(
                f'<li class="g-item-sortable" data-id="{asin}">'
                f'  <h2><a id="itemName_{asin}" href="/dp/{asin}/ref=foo">{title}</a></h2>'
                f'</li>'
            )
        else:
            li_tags.append(
                f'<li class="g-item-sortable">'
                f'  <a href="/dp/{asin}/ref=foo">{title}</a>'
                f'</li>'
            )
    return f'''
    <html><body>
      <ul id="g-items">
        {''.join(li_tags)}
      </ul>
    </body></html>
    '''


class TestExtractWishlistItemsFromHtml:
    def test_basic_extraction_via_data_id(self):
        html = _build_wishlist_html([
            ("B08N5WRWNW", "商品 A"),
            ("B098765432", "商品 B"),
            ("B0ABCDEFGH", "商品 C"),
        ])
        items = extract_wishlist_items_from_html(html)
        assert [it["asin"] for it in items] == ["B08N5WRWNW", "B098765432", "B0ABCDEFGH"]
        # URL は /dp/<ASIN> 形式に正規化されている
        assert items[0]["url"] == "https://www.amazon.co.jp/dp/B08N5WRWNW"

    def test_dedupes_same_asin(self):
        html = _build_wishlist_html([
            ("B08N5WRWNW", "A"),
            ("B098765432", "B"),
            ("B08N5WRWNW", "A duplicate"),
        ])
        items = extract_wishlist_items_from_html(html)
        asins = [it["asin"] for it in items]
        assert asins == ["B08N5WRWNW", "B098765432"]

    def test_fallback_when_data_id_missing(self):
        # data-id が無くても a[href*='/dp/'] フォールバックで拾える
        html = _build_wishlist_html([
            ("B11111CCCC", "fallback A"),
            ("B22222DDDD", "fallback B"),
        ], use_data_id=False)
        items = extract_wishlist_items_from_html(html)
        assert [it["asin"] for it in items] == ["B11111CCCC", "B22222DDDD"]

    def test_invalid_data_id_falls_through_to_anchor(self):
        # data-id が壊れている (10 文字未満) なら、内部 a 要素から抽出
        html = '''
        <html><body>
          <ul id="g-items">
            <li class="g-item-sortable" data-id="BROKEN">
              <a href="/dp/B08N5WRWNW/ref=foo">商品</a>
            </li>
          </ul>
        </body></html>
        '''
        items = extract_wishlist_items_from_html(html)
        assert [it["asin"] for it in items] == ["B08N5WRWNW"]

    def test_lowercase_data_id_normalized_to_upper(self):
        html = '''
        <html><body>
          <ul id="g-items">
            <li class="g-item-sortable" data-id="b08n5wrwnw">x</li>
          </ul>
        </body></html>
        '''
        items = extract_wishlist_items_from_html(html)
        assert [it["asin"] for it in items] == ["B08N5WRWNW"]

    def test_empty_html(self):
        assert extract_wishlist_items_from_html("<html><body></body></html>") == []
        assert extract_wishlist_items_from_html("") == []

    def test_ignores_non_wishlist_anchors(self):
        # ul#g-items 外の a[href*='/dp/'] は対象外
        html = '''
        <html><body>
          <ul id="g-items">
            <li class="g-item-sortable" data-id="B08N5WRWNW">target</li>
          </ul>
          <a href="/dp/B99999999X">noise (outside #g-items)</a>
        </body></html>
        '''
        items = extract_wishlist_items_from_html(html)
        assert [it["asin"] for it in items] == ["B08N5WRWNW"]

    def test_no_g_items_returns_empty(self):
        # ul#g-items 自体が無い → 空配列 (誤って他要素を拾わない)
        html = '''
        <html><body>
          <ul id="other-list">
            <li><a href="/dp/B08N5WRWNW">x</a></li>
          </ul>
        </body></html>
        '''
        assert extract_wishlist_items_from_html(html) == []
