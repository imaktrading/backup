"""tests/test_mercari_seller - メルカリセラー抽出 offline tests."""
from __future__ import annotations

import pytest

from scrapers.mercari_seller import (
    DEFAULT_USER_LIMIT,
    HARD_CAP_PER_SESSION,
    SELLER_PROFILE_URL_RE,
    build_seller_profile_url,
    group_items_by_card_id,
    parse_seller_id,
    resolve_effective_cap,
)


pytestmark = pytest.mark.offline


# --------------------------------------------------------------------------
# parse_seller_id
# --------------------------------------------------------------------------
class TestParseSellerId:
    def test_basic(self):
        assert parse_seller_id("https://jp.mercari.com/user/profile/623636774") == "623636774"

    def test_with_query(self):
        assert parse_seller_id(
            "https://jp.mercari.com/user/profile/623636774?ref=foo"
        ) == "623636774"

    def test_with_fragment(self):
        assert parse_seller_id(
            "https://jp.mercari.com/user/profile/623636774#section"
        ) == "623636774"

    def test_with_trailing_path(self):
        # 追加 path がついても先頭の数字を取る
        assert parse_seller_id(
            "https://jp.mercari.com/user/profile/623636774/items"
        ) == "623636774"

    def test_shops_url_not_matched(self):
        # /shops/* は Phase 1 非対応 → None
        assert parse_seller_id("https://jp.mercari.com/shops/product/abc123") is None
        assert parse_seller_id("https://jp.mercari.com/shops/page/12345") is None

    def test_other_mercari_paths_not_matched(self):
        assert parse_seller_id("https://jp.mercari.com/item/m12345") is None
        assert parse_seller_id("https://jp.mercari.com/mypage/favorites") is None

    def test_empty(self):
        assert parse_seller_id("") is None
        assert parse_seller_id(None) is None  # type: ignore[arg-type]

    def test_non_mercari(self):
        assert parse_seller_id("https://example.com/user/profile/123") is None


# --------------------------------------------------------------------------
# build_seller_profile_url
# --------------------------------------------------------------------------
class TestBuildSellerProfileUrl:
    def test_basic(self):
        assert build_seller_profile_url("623636774") == "https://jp.mercari.com/user/profile/623636774"

    def test_round_trip(self):
        sid = "623636774"
        url = build_seller_profile_url(sid)
        assert parse_seller_id(url) == sid


# --------------------------------------------------------------------------
# resolve_effective_cap
# --------------------------------------------------------------------------
class TestResolveEffectiveCap:
    def test_none_returns_hard_cap(self):
        # 無制限希望 → HARD_CAP_PER_SESSION
        assert resolve_effective_cap(None) == HARD_CAP_PER_SESSION

    def test_zero_returns_hard_cap(self):
        # 0 = 無制限希望扱い
        assert resolve_effective_cap(0) == HARD_CAP_PER_SESSION

    def test_negative_returns_hard_cap(self):
        assert resolve_effective_cap(-10) == HARD_CAP_PER_SESSION

    def test_under_hard_cap_returns_user_limit(self):
        # ユーザー上限 < HARD_CAP → ユーザー上限採用
        assert resolve_effective_cap(25) == 25
        assert resolve_effective_cap(100) == 100

    def test_over_hard_cap_returns_hard_cap(self):
        # ユーザー上限 > HARD_CAP → HARD_CAP で打切
        assert resolve_effective_cap(500) == HARD_CAP_PER_SESSION
        assert resolve_effective_cap(1000) == HARD_CAP_PER_SESSION

    def test_at_hard_cap_boundary(self):
        assert resolve_effective_cap(HARD_CAP_PER_SESSION) == HARD_CAP_PER_SESSION
        assert resolve_effective_cap(HARD_CAP_PER_SESSION + 1) == HARD_CAP_PER_SESSION

    def test_default_user_limit_under_hard_cap(self):
        # DEFAULT_USER_LIMIT (= 25) は HARD_CAP (= 150) 未満
        assert DEFAULT_USER_LIMIT < HARD_CAP_PER_SESSION
        assert resolve_effective_cap(DEFAULT_USER_LIMIT) == DEFAULT_USER_LIMIT


# --------------------------------------------------------------------------
# group_items_by_card_id (= 案 D: 同 card_id 主 + 補)
# --------------------------------------------------------------------------
def _item(url, title, price=None):
    return {"url": url, "title": title, "price_jpy": price}


class TestGroupItemsByCardId:
    def test_single_item_no_card_id(self):
        # title に card_id なし → 単独 row、 auxiliary なし
        items = [_item("https://jp.mercari.com/item/m111", "ワンピース カード ナミ", 5000)]
        result = group_items_by_card_id(items)
        assert len(result) == 1
        assert result[0]["url"] == "https://jp.mercari.com/item/m111"
        assert "auxiliary_urls" not in result[0]

    def test_single_item_with_card_id(self):
        # title に card_id あり、 単独 item → 主のみ、 auxiliary 空 list
        items = [_item("https://jp.mercari.com/item/m111",
                       "ナミ OP01-016 PSA10 R-P プロモ", 5000)]
        result = group_items_by_card_id(items)
        assert len(result) == 1
        assert result[0]["auxiliary_urls"] == []

    def test_two_items_same_card_id_cheapest_is_main(self):
        # 同 card_id 2 件 → 安い方が主、 高い方が aux
        items = [
            _item("https://jp.mercari.com/item/m222",
                  "ワンピース ナミ OP01-016 R-P", 8000),
            _item("https://jp.mercari.com/item/m111",
                  "ナミ OP01-016 R-P プロモ PSA10", 5000),
        ]
        result = group_items_by_card_id(items)
        assert len(result) == 1
        row = result[0]
        assert row["url"] == "https://jp.mercari.com/item/m111"  # = 安い方
        assert row["auxiliary_urls"] == ["https://jp.mercari.com/item/m222"]

    def test_multiple_same_card_id_sorted_by_price(self):
        # 同 card_id 4 件 → 主 = 最安、 aux = 残り 価格昇順
        items = [
            _item("https://jp.mercari.com/item/m333",
                  "ナミ OP01-016 ④", 12000),
            _item("https://jp.mercari.com/item/m111",
                  "ナミ OP01-016 ①", 5000),
            _item("https://jp.mercari.com/item/m222",
                  "ナミ OP01-016 ②", 8000),
            _item("https://jp.mercari.com/item/m444",
                  "ナミ OP01-016 ③", 10000),
        ]
        result = group_items_by_card_id(items)
        assert len(result) == 1
        row = result[0]
        # 主 = 最安 m111
        assert row["url"] == "https://jp.mercari.com/item/m111"
        # aux = 価格昇順 (m222 → m444 → m333)
        assert row["auxiliary_urls"] == [
            "https://jp.mercari.com/item/m222",
            "https://jp.mercari.com/item/m444",
            "https://jp.mercari.com/item/m333",
        ]

    def test_multiple_card_id_groups(self):
        # 異なる card_id 複数 group + card_id なし item 混在
        items = [
            _item("https://jp.mercari.com/item/m100",
                  "ナミ OP01-016", 5000),
            _item("https://jp.mercari.com/item/m200",
                  "ナミ OP01-016 別出品", 7000),
            _item("https://jp.mercari.com/item/m300",
                  "ルフィ ST16-001 PSA10", 8000),
            _item("https://jp.mercari.com/item/m400",
                  "謎のカード (= card_id なし)", 3000),
        ]
        result = group_items_by_card_id(items)
        assert len(result) == 3
        # m100 (OP01-016 主) + m300 (ST16-001 単独) + m400 (単独 = card_id なし)
        urls = [r["url"] for r in result]
        assert "https://jp.mercari.com/item/m100" in urls
        assert "https://jp.mercari.com/item/m300" in urls
        assert "https://jp.mercari.com/item/m400" in urls
        # OP01-016 group の row だけ auxiliary あり
        op_row = next(r for r in result if r["url"] == "https://jp.mercari.com/item/m100")
        assert op_row["auxiliary_urls"] == ["https://jp.mercari.com/item/m200"]

    def test_aux_max_5(self):
        # 同 card_id 8 件 → 主 + aux 5 件 (= AC-AG 5 列分)
        items = [
            _item(f"https://jp.mercari.com/item/m{i:03d}",
                  f"ナミ OP01-016 #{i}", 1000 * i)
            for i in range(1, 9)
        ]
        result = group_items_by_card_id(items)
        assert len(result) == 1
        row = result[0]
        # 主 = m001 (最安)、 aux = m002 - m006 (= 5 件) + m007/m008 は overflow
        assert row["url"] == "https://jp.mercari.com/item/m001"
        assert len(row["auxiliary_urls"]) == 5
        assert row["auxiliary_urls"] == [
            "https://jp.mercari.com/item/m002",
            "https://jp.mercari.com/item/m003",
            "https://jp.mercari.com/item/m004",
            "https://jp.mercari.com/item/m005",
            "https://jp.mercari.com/item/m006",
        ]

    def test_price_none_goes_to_end(self):
        # price=None (= 詳細取得失敗) は最後に回される (= main 候補から外れる)
        items = [
            _item("https://jp.mercari.com/item/m_none",
                  "ナミ OP01-016 価格不明", None),
            _item("https://jp.mercari.com/item/m_low",
                  "ナミ OP01-016 安め", 5000),
        ]
        result = group_items_by_card_id(items)
        assert len(result) == 1
        row = result[0]
        assert row["url"] == "https://jp.mercari.com/item/m_low"  # = price ある方が主
        assert row["auxiliary_urls"] == ["https://jp.mercari.com/item/m_none"]

    def test_empty_input(self):
        assert group_items_by_card_id([]) == []

    def test_st_eb_p_series_also_grouped(self):
        # OP 以外の TCG card_id (= ST/EB/P) でも group 化
        items_st = [
            _item("https://jp.mercari.com/item/m100", "ルフィ ST16-001 a", 5000),
            _item("https://jp.mercari.com/item/m200", "ルフィ ST16-001 b", 7000),
        ]
        result = group_items_by_card_id(items_st)
        assert len(result) == 1
        assert result[0]["auxiliary_urls"] == ["https://jp.mercari.com/item/m200"]


# --------------------------------------------------------------------------
# Constants / config 健全性
# --------------------------------------------------------------------------
class TestConstants:
    def test_hard_cap_positive(self):
        assert HARD_CAP_PER_SESSION > 0
        # 過度に大きい値 (= 1000 件級) を許容しない
        assert HARD_CAP_PER_SESSION <= 200

    def test_default_user_limit_positive(self):
        assert DEFAULT_USER_LIMIT > 0

    def test_default_under_hard_cap(self):
        # default 値は HARD_CAP 未満であるべき (= ユーザー体験)
        assert DEFAULT_USER_LIMIT <= HARD_CAP_PER_SESSION
