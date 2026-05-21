"""tests/test_snkrdunk_favorites - SNKRDUNK お気に入り抽出 offline tests."""
from __future__ import annotations

import pytest

from scrapers.snkrdunk_favorites import (
    FAVORITES_URL_CANDIDATES,
    HOME_URL,
    SNKRDUNK_AUTH_COOKIE_NAME,
    normalize_apparel_used_url,
    parse_apparel_used_url,
)


pytestmark = pytest.mark.offline


# --------------------------------------------------------------------------
# parse_apparel_used_url
# --------------------------------------------------------------------------
class TestParseApparelUsedUrl:
    def test_basic(self):
        assert parse_apparel_used_url(
            "https://snkrdunk.com/apparels/158327/used/45549454"
        ) == (158327, 45549454)

    def test_with_query(self):
        assert parse_apparel_used_url(
            "https://snkrdunk.com/apparels/158327/used/45549454?ref=likes"
        ) == (158327, 45549454)

    def test_with_fragment(self):
        assert parse_apparel_used_url(
            "https://snkrdunk.com/apparels/158327/used/45549454#top"
        ) == (158327, 45549454)

    def test_uppercase_scheme(self):
        assert parse_apparel_used_url(
            "HTTPS://snkrdunk.com/apparels/158327/used/45549454"
        ) == (158327, 45549454)

    def test_apparel_only_not_match(self):
        # /used/ なしはお気に入り URL として無効
        assert parse_apparel_used_url("https://snkrdunk.com/apparels/158327") is None
        assert parse_apparel_used_url("https://snkrdunk.com/apparels/158327/") is None

    def test_not_snkrdunk(self):
        assert parse_apparel_used_url("https://example.com/apparels/1/used/2") is None
        assert parse_apparel_used_url("https://jp.mercari.com/item/m12345") is None

    def test_empty(self):
        assert parse_apparel_used_url("") is None
        assert parse_apparel_used_url(None) is None  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# normalize_apparel_used_url
# --------------------------------------------------------------------------
class TestNormalizeApparelUsedUrl:
    def test_strip_query(self):
        assert normalize_apparel_used_url(
            "https://snkrdunk.com/apparels/158327/used/45549454?ref=likes&foo=bar"
        ) == "https://snkrdunk.com/apparels/158327/used/45549454"

    def test_strip_fragment(self):
        assert normalize_apparel_used_url(
            "https://snkrdunk.com/apparels/158327/used/45549454#top"
        ) == "https://snkrdunk.com/apparels/158327/used/45549454"

    def test_invalid_returns_none(self):
        assert normalize_apparel_used_url("https://example.com/foo") is None
        assert normalize_apparel_used_url("") is None


# --------------------------------------------------------------------------
# 定数 / config 健全性
# --------------------------------------------------------------------------
class TestConstants:
    def test_home_url(self):
        assert HOME_URL == "https://snkrdunk.com/"

    def test_favorites_url_candidates_nonempty(self):
        assert isinstance(FAVORITES_URL_CANDIDATES, list)
        assert len(FAVORITES_URL_CANDIDATES) >= 1
        # 全候補が snkrdunk.com ドメイン配下
        for u in FAVORITES_URL_CANDIDATES:
            assert u.startswith("https://snkrdunk.com/")

    def test_confirmed_favorites_url_first(self):
        # 実機検証で確定した URL (= /accounts/favorites) が候補の先頭
        assert FAVORITES_URL_CANDIDATES[0] == "https://snkrdunk.com/accounts/favorites"

    def test_auth_cookie_name(self):
        assert SNKRDUNK_AUTH_COOKIE_NAME == "auth_session"
