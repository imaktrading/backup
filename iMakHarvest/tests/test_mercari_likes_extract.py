"""tests/test_mercari_likes_extract - extract_likes_from_html / parse_item_id の単体テスト.

Selenium / 認証は使わず、文字列ベースで HTML 抽出ロジックのみ検証する。
DOM 仕様変更を CI で検知するための offline テスト。
"""
from __future__ import annotations

import pytest

from scrapers.mercari_likes import extract_likes_from_html, parse_item_id


pytestmark = pytest.mark.offline


# --------------------------------------------------------------------------
# parse_item_id
# --------------------------------------------------------------------------
class TestParseItemId:
    def test_item_url(self):
        assert parse_item_id("https://jp.mercari.com/item/m12345678901") == "m12345678901"

    def test_items_url_alt(self):
        assert parse_item_id("https://jp.mercari.com/items/m99999999999") == "m99999999999"

    def test_relative_url(self):
        assert parse_item_id("/item/m11111111111") == "m11111111111"

    def test_with_query_string(self):
        assert parse_item_id("https://jp.mercari.com/item/m22222222222?ref=likes") == "m22222222222"

    def test_shops_url_returns_none(self):
        # 本モジュールは通常品のみ対象 (Mercari Shops は別 scraper)
        assert parse_item_id("https://jp.mercari.com/shops/product/abcde-fghij") is None

    def test_empty(self):
        assert parse_item_id("") is None
        assert parse_item_id(None) is None  # type: ignore[arg-type]

    def test_garbage(self):
        assert parse_item_id("https://example.com/foo/bar") is None


# --------------------------------------------------------------------------
# extract_likes_from_html
# --------------------------------------------------------------------------
def _build_likes_html(item_ids: list[str], use_testid: bool = True) -> str:
    """data-testid 付き / 無しを切り替えてダミーいいねページ HTML を生成."""
    anchors = []
    for iid in item_ids:
        if use_testid:
            anchors.append(
                f'<a data-testid="mercari-liked-item" href="/item/{iid}">name</a>'
            )
        else:
            anchors.append(f'<a href="/item/{iid}">name</a>')
    return f"<html><body>{''.join(anchors)}</body></html>"


class TestExtractLikesFromHtml:
    def test_basic_extraction(self):
        html = _build_likes_html(["m11111111111", "m22222222222", "m33333333333"])
        items = extract_likes_from_html(html)
        assert [it["item_id"] for it in items] == ["m11111111111", "m22222222222", "m33333333333"]
        # URL は絶対化されている
        assert all(it["url"].startswith("https://jp.mercari.com/item/") for it in items)

    def test_dedupes_same_item_id(self):
        html = _build_likes_html(["m11111111111", "m22222222222", "m11111111111"])
        items = extract_likes_from_html(html)
        ids = [it["item_id"] for it in items]
        assert ids == ["m11111111111", "m22222222222"]

    def test_fallback_when_testid_missing(self):
        # data-testid が外れた場合、a[href*='item/'] フォールバックで拾える
        html = _build_likes_html(["m44444444444"], use_testid=False)
        items = extract_likes_from_html(html)
        assert [it["item_id"] for it in items] == ["m44444444444"]

    def test_ignores_non_item_anchors(self):
        html = '''
        <html><body>
          <a data-testid="mercari-liked-item" href="/item/m55555555555">x</a>
          <a href="/category/foo">x</a>
          <a href="https://help.mercari.com/">x</a>
        </body></html>
        '''
        items = extract_likes_from_html(html)
        assert [it["item_id"] for it in items] == ["m55555555555"]

    def test_absolute_url_passes_through(self):
        html = (
            '<a data-testid="mercari-liked-item" '
            'href="https://jp.mercari.com/item/m66666666666?ref=likes">x</a>'
        )
        items = extract_likes_from_html(html)
        assert items[0]["url"] == "https://jp.mercari.com/item/m66666666666?ref=likes"
        assert items[0]["item_id"] == "m66666666666"

    def test_empty_html(self):
        assert extract_likes_from_html("<html><body></body></html>") == []
        assert extract_likes_from_html("") == []
