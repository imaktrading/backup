"""mercari_search_api の純関数テスト."""
from scrapers.mercari_search_api import item_url_or_none


def test_item_url_regular():
    assert item_url_or_none("m123", "ITEM") == "https://jp.mercari.com/item/m123"


def test_item_url_shops_excluded():
    """既存Chrome版検索もShopsは拾わず、下流detail fetchも/item/前提のため対象外にする
    (2026-10-02: Shops混入でfetch_failが増えた事故の修正)."""
    assert item_url_or_none("m123", "BEYOND_MERCHANDISE") is None
    assert item_url_or_none("m123", "beyond") is None


def test_item_url_empty_type_defaults_regular():
    assert item_url_or_none("m123", "") == "https://jp.mercari.com/item/m123"
    assert item_url_or_none("m123", None) == "https://jp.mercari.com/item/m123"
