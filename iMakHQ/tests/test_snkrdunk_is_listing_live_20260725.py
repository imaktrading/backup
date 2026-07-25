"""snkrdunk is_listing_live(監視くん消込のsold検知primitive)の純関数テスト (2026-07-25)。

snkrdunk CSR化でページscrape sold検知が壊れ偽sold量産 → HQの used-listings API(CSR非依存)の
listing_id 突合で「その個別出品が今も販売中か」を判定。fail-closed(API失敗=uncertain=消さない)。
純関数のみ(network非依存)。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from snkrdunk_psa_resource import _live_from_listings, _parse_listing_url


def test_parse_listing_url():
    assert _parse_listing_url("https://snkrdunk.com/apparels/434898/used/47178192") == ("434898", "47178192")
    assert _parse_listing_url("https://snkrdunk.com/apparels/434898") == (None, None)  # card page
    assert _parse_listing_url("https://jp.mercari.com/item/m123") == (None, None)      # 別サイト
    assert _parse_listing_url("") == (None, None)
    assert _parse_listing_url(None) == (None, None)


def test_live_from_listings_membership():
    listings = [{"listing_id": 47178192, "price": 9000}, {"listing_id": 44574530, "price": 9000}]
    assert _live_from_listings("47178192", listings) is True        # 在庫一覧に在る=live
    assert _live_from_listings(47178192, listings) is True          # int/str 混在OK
    assert _live_from_listings("99999999", listings) is False       # 無い=sold
    assert _live_from_listings("47178192", []) is False             # 空一覧(card売切)=sold
    assert _live_from_listings("47178192", None) is False           # None→[]扱い(呼出側でuncertain分岐)
