"""URL extractor unit tests (offline)."""

import pytest

from dedupe.extractors.url import (
    extract_mercari_item_id,
    extract_mercari_shops_id,
    extract_mercari_url_key,
)

pytestmark = pytest.mark.offline


class TestItem:
    def test_normal(self):
        url = "https://jp.mercari.com/item/m12345678901"
        assert extract_mercari_item_id(url) == "m12345678901"

    def test_query_params(self):
        url = "https://jp.mercari.com/item/m99999?afid=abc"
        assert extract_mercari_item_id(url) == "m99999"

    def test_shops_url_miss(self):
        url = "https://jp.mercari.com/shops/product/abc-def"
        assert extract_mercari_item_id(url) is None


class TestShops:
    def test_normal(self):
        url = "https://jp.mercari.com/shops/product/abc-def-123"
        assert extract_mercari_shops_id(url) == "abc-def-123"

    def test_item_url_miss(self):
        url = "https://jp.mercari.com/item/m12345"
        assert extract_mercari_shops_id(url) is None


class TestUnifiedKey:
    def test_item_prefix(self):
        assert (
            extract_mercari_url_key("https://jp.mercari.com/item/m12345")
            == "item:m12345"
        )

    def test_shops_prefix(self):
        assert (
            extract_mercari_url_key("https://jp.mercari.com/shops/product/abc-def")
            == "shops:abc-def"
        )

    @pytest.mark.parametrize(
        "url",
        [
            "",
            None,
            "https://example.com/foo",
            "https://www.amazon.co.jp/dp/B0XYZ",
        ],
    )
    def test_fail_closed(self, url):
        assert extract_mercari_url_key(url) is None
