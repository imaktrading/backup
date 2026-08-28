# -*- coding: utf-8 -*-
"""SNKRDUNK 実カード画像(thumbnailUrl)を RESTOCK確証へ流す配線の回帰テスト (2026-06-19)。

真因: RESTOCK確証の SNKRDUNK 候補が listing ページの og:image を拾い、全候補が同じ
サイト既定ロゴになっていた。search API の thumbnailUrl(実カード画像)を resolve_card_id→
check_by_keyword→combine→候補 と流して直す。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

import snkrdunk_psa_resource as sp
import psa_resource_gate as gate


# ★2026-08-28: 採用条件が「番号一致 かつ set 確証」になったので、name に set 名を入れ
#   hint を渡して呼ぶ (依頼書 hq/requests/2026-08-28_restock_search_returned_wrong_cards.md)。
_HINT_OP11 = ["BOOSTER -A FIST OF DIVINE SPEED- [OP-11]", "ブースターパック 神速の拳【OP-11】",
              "A Fist of Divine Speed", "", "R", "ゾロ"]

_SEARCH = {
    "tradingCards": [
        {"id": 520553, "productNumber": "OP11-106",
         "name": '[OP11-106] ゾロ (Booster Pack "A Fist of Divine Speed")',
         "thumbnailUrl": "https://cdn.snkrdunk.com/upload_bg_removed/zoro.webp?size=m"},
    ]
}


def test_match_item_returns_item_with_thumbnail():
    it = sp._match_item(_SEARCH, "OP11-106", variant_hint=_HINT_OP11)
    assert it["id"] == 520553
    assert it["thumbnailUrl"].endswith("zoro.webp?size=m")


def test_parse_search_for_card_still_returns_id():
    """後方互換: parse_search_for_card は従来どおり id (int) を返す。"""
    assert sp.parse_search_for_card(_SEARCH, "OP11-106", variant_hint=_HINT_OP11) == 520553


def test_resolve_card_id_fills_meta_thumbnail(monkeypatch):
    class _R:
        status_code = 200
        def json(self):
            return _SEARCH
    monkeypatch.setattr(sp.requests, "get", lambda *a, **k: _R())
    meta = {}
    cid = sp.resolve_card_id("OP11-106", _meta=meta, variant_hint=_HINT_OP11)
    assert cid == 520553
    assert meta["thumbnail"].endswith("zoro.webp?size=m")


class _FakeMp:
    def card_meta_for_key(self, k):
        return {"hint": "EGGHEAD CRISIS"}


class _FakeSp:
    def __init__(self, image):
        self.image = image
        self.calls = 0
    def check_by_keyword(self, cn, variant_hint=None):
        self.calls += 1
        return {"available": True, "card_image": self.image}


def test_backfill_adds_card_image_to_stale_cache():
    """card_image 無しの旧キャッシュ → HTTP補完で card_image が乗る(Mercariは触らない)。"""
    cached = {"available": True, "psa10_price_jpy": 30000, "psa10_listings": [{"price": 30000, "url": "u"}]}
    row = {"title": "PSA 10 One Piece #OP11-106", "key": "OP11-106"}
    sp_fake = _FakeSp("https://cdn.snkrdunk.com/real.webp")
    out = gate._backfill_snkr_card_image(cached, row, _FakeMp(), sp_fake)
    assert out["card_image"] == "https://cdn.snkrdunk.com/real.webp"
    assert out["psa10_price_jpy"] == 30000      # 既存データ保持
    assert sp_fake.calls == 1


def test_backfill_skips_when_card_image_present():
    """card_image あり + listings 無し → 再取得しない(補完するものが無い)。"""
    cached = {"available": True, "card_image": "https://cdn.snkrdunk.com/already.webp"}
    sp_fake = _FakeSp("https://cdn.snkrdunk.com/new.webp")
    out = gate._backfill_snkr_card_image(cached, {"title": "x", "key": "OP11-106"}, _FakeMp(), sp_fake)
    assert out["card_image"] == "https://cdn.snkrdunk.com/already.webp"
    assert sp_fake.calls == 0


class _SpListings:
    """psa10_listings_for(cached card_id) で per-listing 写真を返す fake。再 resolve しない。"""
    def __init__(self):
        self.list_calls = 0
        self.kw_calls = 0
    def psa10_listings_for(self, cid, timeout=None):
        self.list_calls += 1
        return [{"price": 30000, "image": "https://cdn.snkrdunk.com/apparel_used_listings/x.jpeg",
                 "url": f"https://snkrdunk.com/apparels/{cid}/used/11"}]
    def check_by_keyword(self, cn, variant_hint=None):
        self.kw_calls += 1
        return {"available": True, "card_image": "THUMB"}


def test_backfill_refetches_when_listings_lack_image_key():
    """旧キャッシュ: card_image は有るが psa10_listings に image キー無し → cached card_id で listings
    だけ取り直し per-listing写真を入れる。候補画像が「開く」URL(個別出品)と一致するようになる。"""
    cached = {"available": True, "card_image": "THUMB", "card_id": 999,
              "psa10_listings": [{"price": 30000, "url": "u"}]}      # image キー無し=旧形式
    sp_fake = _SpListings()
    out = gate._backfill_snkr_card_image(cached, {"title": "x", "key": "OP11-106"}, _FakeMp(), sp_fake)
    assert sp_fake.list_calls == 1                                  # cached card_id で listings 取得
    assert sp_fake.kw_calls == 0                                    # card_image 有り→再resolveしない(ドリフト無し)
    assert out["psa10_listings"][0]["image"].endswith("x.jpeg")     # 出品個別写真が入った
    assert "/used/11" in out["psa10_listings"][0]["url"]            # 同一listing由来(url↔image一致)


def test_backfill_uses_cached_card_id_not_reresolve():
    """補完は cached card_id をそのまま使い、check_by_keyword(再resolve)を呼ばない=変種ドリフト防止。"""
    cached = {"available": True, "card_image": "THUMB", "card_id": 328650,
              "psa10_listings": [{"price": 30000, "url": "u"}]}
    sp_fake = _SpListings()
    gate._backfill_snkr_card_image(cached, {"title": "x", "key": "P-053_PRB01"}, _FakeMp(), sp_fake)
    assert sp_fake.kw_calls == 0                                    # 再resolveゼロ


def test_backfill_skips_when_listings_have_image_key():
    """新形式(image キー有り、空でも)+ card_image 有り → 取り直さない(自己修復後の無駄HTTP回避)。"""
    cached = {"available": True, "card_image": "THUMB", "card_id": 999,
              "psa10_listings": [{"price": 30000, "url": "u", "image": ""}]}
    sp_fake = _SpListings()
    out = gate._backfill_snkr_card_image(cached, {"title": "x", "key": "k"}, _FakeMp(), sp_fake)
    assert sp_fake.list_calls == 0 and sp_fake.kw_calls == 0


def test_backfill_skips_unavailable():
    """在庫なし(End候補)は補完対象外。"""
    cached = {"available": False}
    sp_fake = _FakeSp("https://cdn.snkrdunk.com/x.webp")
    out = gate._backfill_snkr_card_image(cached, {"title": "x", "key": "k"}, _FakeMp(), sp_fake)
    assert "card_image" not in out
    assert sp_fake.calls == 0


def test_parse_psa10_listings_extracts_primary_photo():
    """各PSA10出品の primaryPhoto.imageUrl(出品者の実スラブ写真)を抽出。価格昇順 / PSA10限定。"""
    data = {"apparelUsedItems": [
        {"id": 11, "price": 30000, "displayShortConditionTitle": "PSA 10", "isDisplaySold": False,
         "primaryPhoto": {"imageUrl": "https://cdn.snkrdunk.com/apparel_used_listings/x/1.jpeg"}},
        {"id": 12, "price": 28000, "displayShortConditionTitle": "PSA10", "isDisplaySold": False,
         "primaryPhoto": {}},                                   # 写真無し
        {"id": 13, "price": 5000, "displayShortConditionTitle": "PSA9", "isDisplaySold": False,
         "primaryPhoto": {"imageUrl": "y"}},                    # PSA10でない→除外
    ]}
    out = sp.parse_psa10_listings(data)
    assert [o["listing_id"] for o in out] == [12, 11]           # 価格昇順 / PSA9除外
    assert out[0]["image"] == ""                                # 写真無しは空
    assert out[1]["image"] == "https://cdn.snkrdunk.com/apparel_used_listings/x/1.jpeg"


def test_combine_prefers_per_listing_photo_over_thumbnail():
    """候補画像は **その出品個別の実スラブ写真** を最優先、無い時だけカードthumbnailにフォールバック。"""
    snkr = {
        "available": True, "psa10_price_jpy": 28000, "card_image": "THUMB_FALLBACK",
        "psa10_listings": [
            {"price": 28000, "image": "https://cdn.snkrdunk.com/apparel_used_listings/a.jpeg",
             "url": "https://snkrdunk.com/L/11"},
            {"price": 30000, "image": "", "url": "https://snkrdunk.com/L/22"},   # 写真無し→fallback
        ],
    }
    c = gate.combine(None, snkr)
    imgs = [u["image"] for u in c["snkrdunk_urls"]]
    assert imgs[0] == "https://cdn.snkrdunk.com/apparel_used_listings/a.jpeg"    # per-listing 写真
    assert imgs[1] == "THUMB_FALLBACK"                                          # 無い時だけthumbnail
