"""tests/test_snkrdunk_favorites - SNKRDUNK お気に入り抽出 offline tests."""
from __future__ import annotations

import pytest

from scrapers.snkrdunk_favorites import (
    FAVORITES_URL_CANDIDATES,
    HOME_URL,
    SNKRDUNK_AUTH_COOKIE_NAME,
    SNKRDUNK_AUX_PRICE_TOLERANCE_MULTIPLIER,
    _compute_max_price,
    _extract_image_urls,
    _get_price_tolerance_multiplier,
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


# --------------------------------------------------------------------------
# 補仕入 価格幅緩和 (= × 1.2 標準、5/22 HQ 確定)
# --------------------------------------------------------------------------
class TestPriceToleranceMultiplier:
    def test_default_multiplier_is_1_2(self):
        assert SNKRDUNK_AUX_PRICE_TOLERANCE_MULTIPLIER == 1.2

    def test_get_multiplier_default(self, monkeypatch):
        # 環境変数未設定 → default
        monkeypatch.delenv("SNKRDUNK_AUX_PRICE_TOLERANCE", raising=False)
        assert _get_price_tolerance_multiplier() == 1.2

    def test_get_multiplier_env_override(self, monkeypatch):
        monkeypatch.setenv("SNKRDUNK_AUX_PRICE_TOLERANCE", "1.5")
        assert _get_price_tolerance_multiplier() == 1.5

    def test_get_multiplier_invalid_env_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("SNKRDUNK_AUX_PRICE_TOLERANCE", "not-a-number")
        assert _get_price_tolerance_multiplier() == 1.2

    def test_get_multiplier_zero_env_falls_back(self, monkeypatch):
        # 0 以下は無効として default 採用
        monkeypatch.setenv("SNKRDUNK_AUX_PRICE_TOLERANCE", "0")
        assert _get_price_tolerance_multiplier() == 1.2

    def test_get_multiplier_negative_env_falls_back(self, monkeypatch):
        monkeypatch.setenv("SNKRDUNK_AUX_PRICE_TOLERANCE", "-1.5")
        assert _get_price_tolerance_multiplier() == 1.2


class TestComputeMaxPrice:
    def test_at_multiplier_returns_floor(self, monkeypatch):
        # default × 1.2: 10000 → 12000
        monkeypatch.delenv("SNKRDUNK_AUX_PRICE_TOLERANCE", raising=False)
        assert _compute_max_price(10000) == 12000

    def test_non_round_floor(self, monkeypatch):
        monkeypatch.delenv("SNKRDUNK_AUX_PRICE_TOLERANCE", raising=False)
        # 7333 × 1.2 = 8799.6 → floor 8799
        assert _compute_max_price(7333) == 8799

    def test_env_override_1_5(self, monkeypatch):
        monkeypatch.setenv("SNKRDUNK_AUX_PRICE_TOLERANCE", "1.5")
        assert _compute_max_price(10000) == 15000

    def test_zero_price_returns_none(self):
        assert _compute_max_price(0) is None

    def test_negative_price_returns_none(self):
        assert _compute_max_price(-100) is None

    def test_none_returns_none(self):
        assert _compute_max_price(None) is None

    def test_non_int_returns_none(self):
        # str や float が渡された場合 (= API 戻り値想定外) は None で fail-closed
        assert _compute_max_price("12000") is None  # type: ignore[arg-type]
        assert _compute_max_price(12000.5) is None  # type: ignore[arg-type]


class TestAuxPriceFilterScenarios:
    """5/22 依頼書 sec 2 で指定された 4 シナリオ + 端ケース."""

    def test_candidate_within_1_1(self, monkeypatch):
        # 元 ¥10,000 / 候補 ¥11,000 → 採用 (= ×1.1 で許容内)
        monkeypatch.delenv("SNKRDUNK_AUX_PRICE_TOLERANCE", raising=False)
        max_p = _compute_max_price(10000)
        assert 11000 <= max_p  # 11000 ≤ 12000 = 採用

    def test_candidate_at_1_2_boundary(self, monkeypatch):
        # 元 ¥10,000 / 候補 ¥12,000 → 採用 (= ×1.2 上限ぎり)
        monkeypatch.delenv("SNKRDUNK_AUX_PRICE_TOLERANCE", raising=False)
        max_p = _compute_max_price(10000)
        assert 12000 <= max_p  # 12000 ≤ 12000 = 採用

    def test_candidate_just_over_1_2(self, monkeypatch):
        # 元 ¥10,000 / 候補 ¥12,001 → 不採用 (= 上限超)
        monkeypatch.delenv("SNKRDUNK_AUX_PRICE_TOLERANCE", raising=False)
        max_p = _compute_max_price(10000)
        assert 12001 > max_p  # 12001 > 12000 = 不採用

    def test_candidate_below_base(self, monkeypatch):
        # 元 ¥10,000 / 候補 ¥9,000 → 採用 (= 元価格以下は無条件採用)
        monkeypatch.delenv("SNKRDUNK_AUX_PRICE_TOLERANCE", raising=False)
        max_p = _compute_max_price(10000)
        assert 9000 <= max_p  # 9000 ≤ 12000 = 採用
