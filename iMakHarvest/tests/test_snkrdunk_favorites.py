"""tests/test_snkrdunk_favorites - SNKRDUNK お気に入り抽出 offline tests."""
from __future__ import annotations

import pytest

from scrapers.snkrdunk_favorites import (
    FAVORITES_URL_CANDIDATES,
    HOME_URL,
    SNKRDUNK_AUTH_COOKIE_NAME,
    _extract_image_urls,
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


# --------------------------------------------------------------------------
# _extract_image_urls
# --------------------------------------------------------------------------
class TestExtractImageUrls:
    def test_instance_image_urls_list_primary(self):
        # instance.imageUrls (= list) があれば最優先で使う
        agg = {"primaryMedia": {"imageUrl": "https://cdn/agg.webp"}}
        instance = {
            "imageUrls": [
                "https://cdn/inst-1.jpeg",
                "https://cdn/inst-2.jpeg",
                "https://cdn/inst-3.jpeg",
            ],
            "primaryPhoto": {"imageUrl": "https://cdn/pp.jpeg"},
        }
        urls = _extract_image_urls(agg, instance)
        assert urls == [
            "https://cdn/inst-1.jpeg",
            "https://cdn/inst-2.jpeg",
            "https://cdn/inst-3.jpeg",
        ]

    def test_instance_image_urls_filters_non_string(self):
        # list に str 以外混じり → str だけ採用
        instance = {"imageUrls": ["https://cdn/1.jpeg", None, 42, "https://cdn/2.jpeg", ""]}
        assert _extract_image_urls(None, instance) == [
            "https://cdn/1.jpeg",
            "https://cdn/2.jpeg",
        ]

    def test_instance_primary_photo_fallback(self):
        # imageUrls なし or 空 → primaryPhoto.imageUrl 単体
        instance = {"primaryPhoto": {"imageUrl": "https://cdn/pp.jpeg"}, "imageUrls": []}
        urls = _extract_image_urls(None, instance)
        assert urls == ["https://cdn/pp.jpeg"]

    def test_aggregate_primary_media_when_no_instance(self):
        # instance なし → aggregate.primaryMedia.imageUrl
        agg = {"primaryMedia": {"imageUrl": "https://cdn/agg.webp"}}
        urls = _extract_image_urls(agg, None)
        assert urls == ["https://cdn/agg.webp"]

    def test_aggregate_primary_media_fallback_when_instance_empty(self):
        # instance あるが imageUrls / primaryPhoto 両方なし → aggregate を使う
        agg = {"primaryMedia": {"imageUrl": "https://cdn/agg.webp"}}
        instance = {"id": 1}  # 画像 field なし
        urls = _extract_image_urls(agg, instance)
        assert urls == ["https://cdn/agg.webp"]

    def test_both_none(self):
        assert _extract_image_urls(None, None) == []

    def test_empty_dicts(self):
        assert _extract_image_urls({}, {}) == []

    def test_primary_media_non_dict_ignored(self):
        # primaryMedia が str や list の場合 → ignore (= fail-closed)
        agg = {"primaryMedia": "https://cdn/raw.jpg"}
        assert _extract_image_urls(agg, None) == []

    def test_primary_photo_missing_image_url(self):
        instance = {"primaryPhoto": {"id": 1}}  # imageUrl key なし
        assert _extract_image_urls(None, instance) == []

    def test_image_urls_not_list_ignored(self):
        # imageUrls が dict 等 list 以外 → 無視して primaryPhoto fallback
        instance = {
            "imageUrls": {"weird": "shape"},
            "primaryPhoto": {"imageUrl": "https://cdn/pp.jpeg"},
        }
        assert _extract_image_urls(None, instance) == ["https://cdn/pp.jpeg"]
