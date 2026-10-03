"""メルカリ API (mercapi) 判定の対応表 — 2026-10-03 HQ 依頼 watcher_mercari_to_api.

API で確実に読めた時だけ在庫を決め、それ以外は None (= 呼出元が Chrome で見る)。
**読めない時に売切へ倒れないこと**が一番大事。
"""
import sys
import types

import pytest

import scrapers.mercari_scraper as m

pytestmark = pytest.mark.mercari_api


def _install_fake_mercapi(monkeypatch, item=None, product=None, raise_exc=None):
    class FakeMercapi:
        async def item(self, key):
            if raise_exc:
                raise raise_exc
            return item

        async def product(self, key):
            if raise_exc:
                raise raise_exc
            return product

    monkeypatch.setitem(sys.modules, "mercapi", types.SimpleNamespace(Mercapi=FakeMercapi))
    monkeypatch.setattr(m, "MERCARI_API_ENABLED", True)


def _item(status, auction=None, price=1000):
    return types.SimpleNamespace(status=status, auction_info=auction, price=price, name="x")


def _product(quantities, price="2500"):
    variants = [types.SimpleNamespace(quantity=q) for q in quantities]
    return types.SimpleNamespace(price=price, display_name="p",
                                 product_detail=types.SimpleNamespace(variants=variants))


ITEM = "https://jp.mercari.com/item/m123"
SHOPS = "https://jp.mercari.com/shops/product/2JAbc"


def test_item_on_sale(monkeypatch):
    _install_fake_mercapi(monkeypatch, item=_item("on_sale", price=880))
    assert m._detect_via_api(ITEM, False) == {
        "name": "x", "status": "ON_SALE", "in_stock": True, "price_jpy": 880}


@pytest.mark.parametrize("status", ["sold_out", "trading"])
def test_item_sold(monkeypatch, status):
    _install_fake_mercapi(monkeypatch, item=_item(status))
    r = m._detect_via_api(ITEM, False)
    assert r["in_stock"] is False and r["status"] == "SOLD_OUT"


def test_item_auction_is_not_buyable_even_if_on_sale(monkeypatch):
    _install_fake_mercapi(monkeypatch, item=_item("on_sale", auction=object()))
    r = m._detect_via_api(ITEM, False)
    assert r["status"] == "AUCTION" and r["in_stock"] is False


def test_item_unknown_status_goes_to_chrome(monkeypatch):
    _install_fake_mercapi(monkeypatch, item=_item("stop"))
    assert m._detect_via_api(ITEM, False) is None


def test_item_none_goes_to_chrome(monkeypatch):
    _install_fake_mercapi(monkeypatch, item=None)
    assert m._detect_via_api(ITEM, False) is None


def test_exception_goes_to_chrome_not_sold(monkeypatch):
    # 削除済の個人出品は mercapi が KeyError('data') を投げる (実測)
    _install_fake_mercapi(monkeypatch, raise_exc=KeyError("data"))
    assert m._detect_via_api(ITEM, False) is None


def test_shops_quantity_sum(monkeypatch):
    _install_fake_mercapi(monkeypatch, product=_product(["0", "2"]))
    r = m._detect_via_api(SHOPS, True)
    assert r["in_stock"] is True and r["price_jpy"] == 2500


def test_shops_all_zero_is_sold(monkeypatch):
    _install_fake_mercapi(monkeypatch, product=_product(["0"]))
    r = m._detect_via_api(SHOPS, True)
    assert r["in_stock"] is False and r["status"] == "SOLD_OUT"


def test_shops_bad_quantity_goes_to_chrome(monkeypatch):
    _install_fake_mercapi(monkeypatch, product=_product(["?"]))
    assert m._detect_via_api(SHOPS, True) is None


def test_shops_no_variants_goes_to_chrome(monkeypatch):
    _install_fake_mercapi(monkeypatch, product=_product([]))
    assert m._detect_via_api(SHOPS, True) is None


def test_disabled_by_env_switch(monkeypatch):
    _install_fake_mercapi(monkeypatch, item=_item("on_sale"))
    monkeypatch.setattr(m, "MERCARI_API_ENABLED", False)
    assert m._detect_via_api(ITEM, False) is None


def test_fetch_uses_api_and_skips_chrome(monkeypatch):
    _install_fake_mercapi(monkeypatch, item=_item("sold_out", price=500))
    monkeypatch.setattr(m, "_check_404", lambda u: pytest.fail("Chrome 側に来てはいけない"))
    r = m.fetch_product_inventory(ITEM, driver=object())
    assert r["source"] == "api" and r["skus"][0]["in_stock"] is False


def test_fetch_falls_back_to_chrome_when_api_unreadable(monkeypatch):
    _install_fake_mercapi(monkeypatch, raise_exc=RuntimeError("network"))
    monkeypatch.setattr(m, "_check_404", lambda u: False)
    monkeypatch.setattr(m, "_detect_via_selenium", lambda d, u, s: {
        "name": "c", "status": "ON_SALE", "in_stock": True, "price_jpy": 1})
    r = m.fetch_product_inventory(ITEM, driver=object())
    assert "source" not in r and r["skus"][0]["in_stock"] is True


def _product_ts(time_sale, price="7500"):
    p = _product(["1"], price=price)
    p.product_detail.time_sale_details = time_sale
    return p


def test_shops_time_sale_price_used_during_sale(monkeypatch):
    ts = {"price": "5500", "startTime": "2000-01-01T00:00:00Z", "endTime": "2099-01-01T00:00:00Z"}
    _install_fake_mercapi(monkeypatch, product=_product_ts(ts))
    assert m._detect_via_api(SHOPS, True)["price_jpy"] == 5500


def test_shops_time_sale_outside_window_uses_list_price(monkeypatch):
    ts = {"price": "5500", "startTime": "2000-01-01T00:00:00Z", "endTime": "2000-01-02T00:00:00Z"}
    _install_fake_mercapi(monkeypatch, product=_product_ts(ts))
    assert m._detect_via_api(SHOPS, True)["price_jpy"] == 7500


def test_shops_unreadable_time_sale_goes_to_chrome(monkeypatch):
    _install_fake_mercapi(monkeypatch, product=_product_ts({"price": "x"}))
    assert m._detect_via_api(SHOPS, True) is None


def test_spotcheck_takes_sold_when_chrome_disagrees(monkeypatch, tmp_path):
    _install_fake_mercapi(monkeypatch, item=_item("on_sale"))
    monkeypatch.setattr(m, "SPOTCHECK_EVERY", 1)
    monkeypatch.setattr(m, "SPOTCHECK_LOG", str(tmp_path / "s.jsonl"))
    monkeypatch.setattr(m, "_detect_via_selenium", lambda d, u, s: {
        "name": "c", "status": "SOLD_OUT", "in_stock": False, "price_jpy": None})
    r = m.fetch_product_inventory(ITEM, driver=object())
    assert r["skus"][0]["in_stock"] is False
    assert '"mismatch": true' in (tmp_path / "s.jsonl").read_text(encoding="utf-8")


def test_spotcheck_keeps_api_when_chrome_unreadable(monkeypatch, tmp_path):
    _install_fake_mercapi(monkeypatch, item=_item("on_sale"))
    monkeypatch.setattr(m, "SPOTCHECK_EVERY", 1)
    monkeypatch.setattr(m, "SPOTCHECK_LOG", str(tmp_path / "s.jsonl"))
    monkeypatch.setattr(m, "_detect_via_selenium", lambda d, u, s: None)
    assert m.fetch_product_inventory(ITEM, driver=object())["skus"][0]["in_stock"] is True


def test_spotcheck_skipped_between_samples(monkeypatch, tmp_path):
    _install_fake_mercapi(monkeypatch, item=_item("on_sale"))
    monkeypatch.setattr(m, "SPOTCHECK_EVERY", 1000)
    monkeypatch.setattr(m, "_spotcheck_counter", 1)
    monkeypatch.setattr(m, "_detect_via_selenium", lambda d, u, s: pytest.fail("見ない回"))
    assert m.fetch_product_inventory(ITEM, driver=object())["skus"][0]["in_stock"] is True
