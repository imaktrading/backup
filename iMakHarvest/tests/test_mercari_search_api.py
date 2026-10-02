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


class _FakeShipping:
    def __init__(self, id_):
        self.id_ = id_


class _FakeSeller:
    def __init__(self, num_ratings, star, sms="yes"):
        self.num_ratings = num_ratings
        self.star_rating_score = star
        self.register_sms_confirmation = sms


class _FakeItem:
    def __init__(self, status="on_sale", auction_info=None, price=1000, name="x",
                description="d", photos=None, shipping_payer_id=2,
                num_ratings=50, star=4.5, sms="yes"):
        self.status = status
        self.auction_info = auction_info
        self.price = price
        self.name = name
        self.description = description
        self.photos = photos or ["https://a/1.jpg"]
        self.shipping_payer = _FakeShipping(shipping_payer_id)
        self.seller = _FakeSeller(num_ratings, star, sms)


def test_map_item_to_detail_on_sale():
    from scrapers.mercari_search_api import map_item_to_detail
    d = map_item_to_detail(_FakeItem())
    assert d["in_stock"] is True
    assert d["status"] == "ON_SALE"
    assert d["price_jpy"] == 1000
    assert d["shipping_included"] is True
    assert d["seller_quality"]["rating_count"] == 50
    assert d["seller_quality"]["identity_verified"] is True


def test_map_item_to_detail_sms_not_confirmed():
    from scrapers.mercari_search_api import map_item_to_detail
    d = map_item_to_detail(_FakeItem(sms="no"))
    assert d["seller_quality"]["identity_verified"] is False


def test_map_item_to_detail_sold_out():
    from scrapers.mercari_search_api import map_item_to_detail
    d = map_item_to_detail(_FakeItem(status="sold_out"))
    assert d["in_stock"] is False
    assert d["status"] == "SOLD_OUT"


def test_map_item_to_detail_auction_treated_as_unbuyable():
    """オークション中はたとえstatusがon_saleでも買えない扱い (Chrome版と同じ思想)."""
    from scrapers.mercari_search_api import map_item_to_detail
    d = map_item_to_detail(_FakeItem(status="on_sale", auction_info=object()))
    assert d["in_stock"] is False
    assert d["status"] == "SOLD_OUT"


def test_map_item_to_detail_shipping_not_included():
    from scrapers.mercari_search_api import map_item_to_detail
    d = map_item_to_detail(_FakeItem(shipping_payer_id=1))
    assert d["shipping_included"] is False
