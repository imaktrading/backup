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
    pick_card_image_url,
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


# --------------------------------------------------------------------------
# group_items_by_card_id with Vision (= Phase 2、 use_vision=True)
# --------------------------------------------------------------------------
class TestGroupItemsByCardIdWithVision:
    """Vision 補強 mode の group 化動作 (= judge_card_id_from_image_url mock)."""

    def _make_item(self, url, title, image_url, price=1000):
        return {
            "url": url,
            "title": title,
            "price_jpy": price,
            "image_urls": [image_url] if image_url else [],
        }

    def test_vision_disabled_unchanged_behavior(self, monkeypatch):
        # use_vision=False → 既存 title only と同じ挙動
        items = [
            self._make_item("https://jp.mercari.com/item/m100",
                            "ナミ OP01-016", "https://cdn/x.jpg", 5000),
            self._make_item("https://jp.mercari.com/item/m200",
                            "謎のカード", "https://cdn/y.jpg", 3000),
        ]
        # Vision 呼出が起きないことを確認 (= mock しなくても外部呼出ない)
        result = group_items_by_card_id(items, use_vision=False)
        assert len(result) == 2

    def test_vision_picks_up_when_title_empty(self, monkeypatch):
        # title から card_id 取れない → Vision が ST29-003 を返す
        from scrapers import mercari_seller as ms
        monkeypatch.setattr(
            ms, "judge_card_id_from_image_url",
            lambda url, *a, **kw: "ST29-003" if "x" in url else "",
        )
        items = [
            self._make_item("https://jp.mercari.com/item/m100",
                            "PSA10 ST29 カク #003 1799", "https://cdn/x.jpg", 17000),
            self._make_item("https://jp.mercari.com/item/m200",
                            "PSA10 ST29 別出品", "https://cdn/x.jpg", 19000),
        ]
        result = group_items_by_card_id(items, use_vision=True)
        # 2 件とも Vision で ST29-003 → 同 group → 1 row、 安い方が主
        assert len(result) == 1
        assert result[0]["url"] == "https://jp.mercari.com/item/m100"
        assert result[0]["auxiliary_urls"] == ["https://jp.mercari.com/item/m200"]

    def test_vision_none_keeps_item_standalone(self, monkeypatch):
        # Vision が NONE 返却 → title 由来 card_id もないので、 単独 row
        from scrapers import mercari_seller as ms
        monkeypatch.setattr(
            ms, "judge_card_id_from_image_url",
            lambda *a, **kw: "",
        )
        items = [
            self._make_item("https://jp.mercari.com/item/m100",
                            "Pokemon Pikachu", "https://cdn/x.jpg", 5000),
        ]
        result = group_items_by_card_id(items, use_vision=True)
        assert len(result) == 1
        assert "auxiliary_urls" not in result[0]

    def test_vision_overrides_title_on_disagree(self, monkeypatch):
        # title=OP01-001, Vision=OP01-002 → Vision 優先 (= 違うカード扱い)
        from scrapers import mercari_seller as ms
        monkeypatch.setattr(
            ms, "judge_card_id_from_image_url",
            lambda url, *a, **kw: "OP01-002",
        )
        items = [
            self._make_item("https://jp.mercari.com/item/m100",
                            "ナミ OP01-001 (typo)", "https://cdn/x.jpg", 5000),
            self._make_item("https://jp.mercari.com/item/m200",
                            "ナミ OP01-002 正しい", "https://cdn/y.jpg", 6000),
        ]
        # m100 は Vision で OP01-002 (= title typo override)
        # m200 は title から OP01-002 取れる + Vision も OP01-002 (= 一致)
        # = 両方 OP01-002、 1 group、 安い方 m100 が主
        result = group_items_by_card_id(items, use_vision=True)
        assert len(result) == 1
        assert result[0]["url"] == "https://jp.mercari.com/item/m100"
        assert result[0]["auxiliary_urls"] == ["https://jp.mercari.com/item/m200"]

    def test_vision_stats_recorded(self, monkeypatch):
        # vision_stats dict に統計が記録される
        from scrapers import mercari_seller as ms
        monkeypatch.setattr(
            ms, "judge_card_id_from_image_url",
            lambda url, *a, **kw: "OP01-001" if "x" in url else "",
        )
        items = [
            self._make_item("https://jp.mercari.com/item/m100",
                            "ナミ", "https://cdn/x.jpg", 5000),  # Vision で取れる
            self._make_item("https://jp.mercari.com/item/m200",
                            "謎", "https://cdn/y.jpg", 3000),  # Vision 取れない
        ]
        stats = {}
        group_items_by_card_id(items, use_vision=True, vision_stats=stats)
        assert stats["vision_calls"] == 2
        assert stats["vision_hits"] == 1
        assert stats.get("title_vs_vision_disagree", 0) == 0

    def test_vision_disagree_recorded(self, monkeypatch):
        # title と Vision で 不一致時 → 統計に反映
        from scrapers import mercari_seller as ms
        monkeypatch.setattr(
            ms, "judge_card_id_from_image_url",
            lambda *a, **kw: "OP01-002",
        )
        items = [
            self._make_item("https://jp.mercari.com/item/m100",
                            "ナミ OP01-001 typo", "https://cdn/x.jpg", 5000),
        ]
        stats = {}
        group_items_by_card_id(items, use_vision=True, vision_stats=stats)
        assert stats["title_vs_vision_disagree"] == 1

    def test_no_image_falls_back_to_title(self, monkeypatch):
        # image_urls 空 → Vision 呼出さない、 title のみで判定
        from scrapers import mercari_seller as ms
        vision_called = []
        monkeypatch.setattr(
            ms, "judge_card_id_from_image_url",
            lambda *a, **kw: vision_called.append(a) or "OP99-999",
        )
        items = [{"url": "https://jp.mercari.com/item/m100",
                  "title": "ナミ OP01-016",
                  "price_jpy": 5000,
                  "image_urls": []}]  # 画像なし
        result = group_items_by_card_id(items, use_vision=True)
        # Vision 呼出されない (= image_url 空)
        assert len(vision_called) == 0
        # title 由来 OP01-016 で単独 group
        assert len(result) == 1


# --------------------------------------------------------------------------
# pick_card_image_url (= プロフィール画像除外、 商品本体画像優先)
# --------------------------------------------------------------------------
class TestPickCardImageUrl:
    def test_empty_returns_none(self):
        assert pick_card_image_url([]) is None
        assert pick_card_image_url(None) is None  # type: ignore[arg-type]

    def test_only_invalid_returns_none(self):
        # 空文字 / None 混在 → 有効 URL なし → None
        assert pick_card_image_url(["", None, ""]) is None  # type: ignore[list-item]

    def test_item_detail_priority(self):
        # /item/detail/ が含まれていれば最優先
        urls = [
            "https://static.mercdn.net/thumb/members/webp/41.jpg",  # = profile
            "https://static.mercdn.net/item/detail/orig/photos/m99_1.jpg",
            "https://static.mercdn.net/item/detail/orig/photos/m99_2.jpg",
        ]
        result = pick_card_image_url(urls)
        assert "/item/detail/" in result
        assert result == "https://static.mercdn.net/item/detail/orig/photos/m99_1.jpg"

    def test_item_path_secondary_priority(self):
        # /item/detail/ なし、 /item/ あり → 採用
        urls = [
            "https://static.mercdn.net/thumb/members/webp/41.jpg",
            "https://static.mercdn.net/thumb/item/webp/m99_1.jpg",
        ]
        result = pick_card_image_url(urls)
        assert "/item/" in result

    def test_non_profile_fallback(self):
        # /item/ も /item/detail/ もなし、 ただし /thumb/members/ じゃない → 採用
        urls = [
            "https://static.mercdn.net/thumb/members/webp/41.jpg",  # profile
            "https://cdn.something.com/foo.jpg",  # = 別 cdn、 profile じゃない
        ]
        result = pick_card_image_url(urls)
        assert result == "https://cdn.something.com/foo.jpg"

    def test_all_profile_returns_none(self):
        # 全部 profile 画像 → None (= Vision 呼出さない、 fail-closed)
        urls = [
            "https://static.mercdn.net/thumb/members/webp/41.jpg",
            "https://static.mercdn.net/thumb/members/webp/42.jpg",
        ]
        assert pick_card_image_url(urls) is None

    def test_skips_non_string_entries(self):
        urls = [None, 42, "", "https://static.mercdn.net/item/detail/x.jpg"]  # type: ignore[list-item]
        result = pick_card_image_url(urls)
        assert result == "https://static.mercdn.net/item/detail/x.jpg"

    def test_real_world_pattern(self):
        # 実機観察パターン: profile 画像が先頭 + 商品画像が後ろ
        urls = [
            "https://static.mercdn.net/thumb/members/webp/415216906.jpg?1465253168",
            "https://static.mercdn.net/item/detail/orig/photos/m12743012686_1.jpg",
            "https://static.mercdn.net/item/detail/orig/photos/m12743012686_2.jpg",
        ]
        result = pick_card_image_url(urls)
        assert result == "https://static.mercdn.net/item/detail/orig/photos/m12743012686_1.jpg"
