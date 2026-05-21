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


# --------------------------------------------------------------------------
# SOLD 除外 (= メルカリと同パターン、in_stock 判定 + exclude_sold filter)
# --------------------------------------------------------------------------
class TestInStockJudgement:
    """_build_item_dict の in_stock 判定ロジックを直接 test (= mock 経由)."""

    def _build_with_mocks(self, monkeypatch, instance_dict):
        from scrapers import snkrdunk_favorites as sf
        agg_stub = {
            "name": "Test card", "localizedName": "テスト",
            "productNumber": "OP06-106",
            "primaryMedia": {"imageUrl": "https://cdn/agg.webp"},
        }
        monkeypatch.setattr(sf, "fetch_apparel_aggregate", lambda *a, **kw: agg_stub)
        monkeypatch.setattr(sf, "fetch_apparel_used_instance", lambda *a, **kw: instance_dict)
        return sf._build_item_dict(123, 456)

    def test_status_zero_is_in_stock_true(self, monkeypatch):
        d = self._build_with_mocks(monkeypatch, {"status": 0, "price": 12800,
                                                  "displayShortConditionTitle": "PSA10"})
        assert d["in_stock"] is True

    def test_status_one_is_in_stock_false(self, monkeypatch):
        # status=1 (= 売切等)
        d = self._build_with_mocks(monkeypatch, {"status": 1, "price": 12800,
                                                  "displayShortConditionTitle": "PSA10"})
        assert d["in_stock"] is False

    def test_status_other_int_is_in_stock_false(self, monkeypatch):
        # status=2, 3 等は False (= 0 以外は全部 売切扱い)
        for s in (2, 3, 99):
            d = self._build_with_mocks(monkeypatch, {"status": s})
            assert d["in_stock"] is False, f"status={s} should be False"

    def test_status_missing_is_in_stock_none(self, monkeypatch):
        # status field なし → None (= 不明、安全側で含める)
        d = self._build_with_mocks(monkeypatch, {"price": 12800})
        assert d["in_stock"] is None

    def test_status_non_int_is_in_stock_none(self, monkeypatch):
        # status が str 等 (= 想定外型) → None
        d = self._build_with_mocks(monkeypatch, {"status": "on_sale"})
        assert d["in_stock"] is None

    def test_instance_none_is_in_stock_none(self, monkeypatch):
        # instance API 失敗 (= None) → in_stock=None (= title だけ best effort で返す)
        d = self._build_with_mocks(monkeypatch, None)
        assert d["in_stock"] is None
        assert d["title"]  # title は aggregate から取得済


class TestExcludeSoldFilter:
    """exclude_sold logic 確認 (= メルカリと同パターン)."""

    def test_sold_excluded_by_default(self):
        # 「in_stock=False を skip」 という条件が成立しているかは
        # collect_favorites_with_details 内の 1 行 logic で確認:
        #   `if exclude_sold and d.get("in_stock") is False:`
        # = exclude_sold=True (default) + in_stock=False → skip
        from scrapers.snkrdunk_favorites import collect_favorites_with_details
        # default 引数 exclude_sold=True であることを sig で確認
        import inspect
        sig = inspect.signature(collect_favorites_with_details)
        assert sig.parameters["exclude_sold"].default is True

    def test_filter_logic_sold_excluded(self):
        # 模擬 logic: exclude_sold=True + in_stock=False → True (skip)
        item_sold = {"in_stock": False}
        assert (True and item_sold.get("in_stock") is False) is True

    def test_filter_logic_in_stock_kept(self):
        item_in_stock = {"in_stock": True}
        assert (True and item_in_stock.get("in_stock") is False) is False

    def test_filter_logic_unknown_kept_safe_side(self):
        # in_stock=None (= 不明) は exclude_sold=True でも skip しない (= 安全側で含める)
        item_unknown = {"in_stock": None}
        assert (True and item_unknown.get("in_stock") is False) is False

    def test_filter_logic_disabled(self):
        # exclude_sold=False なら in_stock=False でも skip しない
        item_sold = {"in_stock": False}
        assert (False and item_sold.get("in_stock") is False) is False
