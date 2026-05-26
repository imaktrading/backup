"""tests/test_mercari_shops_search - mercari-shops.com 検索抽出 offline tests."""
from __future__ import annotations

import pytest

from scrapers.mercari_shops_search import (
    DEFAULT_USER_LIMIT,
    HARD_CAP_PER_SESSION,
    parse_product_id,
    parse_search_url,
    resolve_effective_cap,
)
from sheet_writer_mercari_shops import build_shops_tab_name


pytestmark = pytest.mark.offline


class TestParseSearchUrl:
    def test_full_url(self):
        url = (
            "https://mercari-shops.com/search?in_dual_price=false&coupon_available=false"
            "&source=&in_shop=true&shop_ids=acTx9sbekaEzMoj8WRF8EJ"
            "&keyword=%E3%82%B5%E3%83%B3%E3%83%AA%E3%82%AA&in_stock=true"
        )
        r = parse_search_url(url)
        assert r is not None
        assert r["shop_id"] == "acTx9sbekaEzMoj8WRF8EJ"
        assert r["keyword"] == "サンリオ"
        assert r["in_stock"] is True
        assert r["raw_url"] == url

    def test_keyword_only(self):
        url = "https://mercari-shops.com/search?keyword=test"
        r = parse_search_url(url)
        assert r is not None
        assert r["shop_id"] is None
        assert r["keyword"] == "test"
        assert r["in_stock"] is True  # default

    def test_in_stock_false(self):
        url = "https://mercari-shops.com/search?keyword=foo&in_stock=false"
        r = parse_search_url(url)
        assert r is not None
        assert r["in_stock"] is False

    def test_wrong_domain(self):
        # jp.mercari.com 配下 (= shop ではなく メルカリ本体) は別 scope
        assert parse_search_url(
            "https://jp.mercari.com/search?keyword=test"
        ) is None

    def test_empty(self):
        assert parse_search_url("") is None
        assert parse_search_url(None) is None  # type: ignore[arg-type]


class TestParseProductId:
    def test_basic(self):
        assert parse_product_id(
            "https://jp.mercari.com/shops/product/2JLQjbFsTCiythGCCpEcQA"
        ) == "2JLQjbFsTCiythGCCpEcQA"

    def test_with_source_query(self):
        assert parse_product_id(
            "https://jp.mercari.com/shops/product/2JLQjbFsTCiythGCCpEcQA"
            "?source=shops_search"
        ) == "2JLQjbFsTCiythGCCpEcQA"

    def test_non_match(self):
        assert parse_product_id("https://jp.mercari.com/item/m12345") is None
        assert parse_product_id("") is None
        assert parse_product_id(None) is None  # type: ignore[arg-type]


class TestResolveEffectiveCap:
    def test_none_returns_default(self):
        # shops は自動 scroll 暴走防止のため None → DEFAULT_USER_LIMIT (= 200)
        assert resolve_effective_cap(None) == min(DEFAULT_USER_LIMIT, HARD_CAP_PER_SESSION)

    def test_zero_returns_default(self):
        assert resolve_effective_cap(0) == min(DEFAULT_USER_LIMIT, HARD_CAP_PER_SESSION)

    def test_negative_returns_default(self):
        assert resolve_effective_cap(-5) == min(DEFAULT_USER_LIMIT, HARD_CAP_PER_SESSION)

    def test_under_cap(self):
        assert resolve_effective_cap(50) == 50

    def test_over_cap(self):
        assert resolve_effective_cap(HARD_CAP_PER_SESSION + 500) == HARD_CAP_PER_SESSION

    def test_default_is_200(self):
        # ユーザー判断 (= 5/26、 自動 scroll 暴走防止)
        assert DEFAULT_USER_LIMIT == 200


class TestBuildShopsTabName:
    def test_shop_id_and_keyword(self):
        n = build_shops_tab_name("ABC123", "サンリオ")
        assert n.startswith("shops_ABC123_")
        assert "サンリオ" in n

    def test_shop_id_only(self):
        assert build_shops_tab_name("ABC123") == "shops_ABC123"

    def test_keyword_only(self):
        n = build_shops_tab_name(None, "テスト")
        assert n.startswith("shops_kw_")
        assert "テスト" in n

    def test_neither(self):
        assert build_shops_tab_name(None, None) == "shops_unknown"

    def test_long_keyword_truncated(self):
        long_kw = "あ" * 100
        n = build_shops_tab_name("X", long_kw)
        # tab 名は max_len=30 で keyword 部分が打切される
        assert len(n) <= len("shops_X_") + 30
