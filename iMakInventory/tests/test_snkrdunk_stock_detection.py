"""snkrdunk_scraper unit + 結合 test.

5/17 commit (Phase 1): スニダン PSA10 監視追加。

判定軸:
  1. HTTP 200 + JSON-LD availability=InStock → IN_STOCK
  2. HTTP 404 → DELETED
  3. HTTP 200 + availability!=InStock → SOLD_OUT
  4. JSON-LD なし / parse 失敗 → UNKNOWN (fail-closed in_stock=False)
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scrapers.snkrdunk_scraper import (  # noqa: E402
    fetch_product_inventory, parse_product_id, _extract_jsonld_product,
)


# ============================================================================
# parse_product_id
# ============================================================================
class TestParseProductId:
    def test_valid_url(self):
        url = "https://snkrdunk.com/apparels/159278/used/45538280"
        assert parse_product_id(url) == "159278:45538280"

    def test_invalid_url(self):
        assert parse_product_id("https://example.com/foo") is None

    def test_empty(self):
        assert parse_product_id("") is None
        assert parse_product_id(None) is None


# ============================================================================
# _extract_jsonld_product
# ============================================================================
class TestExtractJsonld:
    def test_simple_product(self):
        html = (
            '<script type="application/ld+json">'
            '{"@context":"https://schema.org/","@type":"Product",'
            '"productID":"123","name":"Test","offers":{"@type":"Offer",'
            '"price":1000,"availability":"https://schema.org/InStock"}}'
            '</script>'
        )
        p = _extract_jsonld_product(html)
        assert p is not None
        assert p["@type"] == "Product"
        assert p["offers"]["availability"].endswith("InStock")

    def test_no_jsonld(self):
        assert _extract_jsonld_product("<html><body>foo</body></html>") is None

    def test_invalid_json(self):
        html = '<script type="application/ld+json">{invalid json</script>'
        assert _extract_jsonld_product(html) is None


# ============================================================================
# fetch_product_inventory (= mocked requests)
# ============================================================================
def _mock_response(status: int, html: str = "") -> MagicMock:
    m = MagicMock()
    m.status_code = status
    m.text = html
    return m


_HTML_INSTOCK = (
    '<html><script type="application/ld+json">'
    '{"@context":"https://schema.org/","@type":"Product",'
    '"productID":"45538280","name":"Kaya R [OP03-044]",'
    '"offers":{"@type":"Offer","price":8900,'
    '"availability":"https://schema.org/InStock"}}'
    '</script></html>'
)

_HTML_OUTOFSTOCK = (
    '<html><script type="application/ld+json">'
    '{"@type":"Product","name":"X","offers":{'
    '"availability":"https://schema.org/OutOfStock"}}'
    '</script></html>'
)


class TestFetchProductInventory:
    """既存の requests 経路テスト群。is_listing_live(PRIMARY) を None 固定にして requests 経路を検証。"""

    @pytest.fixture(autouse=True)
    def _no_api(self):
        # HQ helper を uncertain 固定 → 従来 requests 経路にフォールバックさせて既存挙動を検証
        with patch("scrapers.snkrdunk_scraper._hq_listing_live_price", return_value=(None, None)):
            yield

    def test_in_stock(self):
        with patch("scrapers.snkrdunk_scraper.requests.get",
                   return_value=_mock_response(200, _HTML_INSTOCK)):
            info = fetch_product_inventory(
                "https://snkrdunk.com/apparels/159278/used/45538280")
        assert info is not None
        assert info["status"] == "IN_STOCK"
        assert info["product_id"] == "159278:45538280"
        assert info["skus"][0]["in_stock"] is True
        assert info["skus"][0]["quantity"] == 1
        assert info["skus"][0]["price_jpy"] == 8900
        assert info["name"] == "Kaya R [OP03-044]"

    def test_404_deleted(self):
        with patch("scrapers.snkrdunk_scraper.requests.get",
                   return_value=_mock_response(404, "")):
            info = fetch_product_inventory(
                "https://snkrdunk.com/apparels/159278/used/99999999")
        assert info is not None
        assert info["status"] == "DELETED"
        assert info["skus"][0]["in_stock"] is False
        assert info["skus"][0]["quantity"] == 0

    def test_sold_out(self):
        with patch("scrapers.snkrdunk_scraper.requests.get",
                   return_value=_mock_response(200, _HTML_OUTOFSTOCK)):
            info = fetch_product_inventory(
                "https://snkrdunk.com/apparels/159278/used/12345")
        assert info is not None
        assert info["status"] == "SOLD_OUT"
        assert info["skus"][0]["in_stock"] is False

    def test_jsonld_missing_is_uncertain_not_sold(self):
        """★ 2026-07-25 fail-closed 修正: 判定不能 → in_stock=None (旧: False=偽sold)。

        snkrdunk CSR 化で jsonld Product が消滅 → 全件「判定不能」。旧実装は in_stock=False に潰し
        「売切確定(is_sold=True)」に化けて偽取下げ/偽消込を量産した。None のまま返し uncertain に倒す。
        """
        with patch("scrapers.snkrdunk_scraper.requests.get",
                   return_value=_mock_response(200, "<html>no jsonld no rsc</html>")):
            info = fetch_product_inventory(
                "https://snkrdunk.com/apparels/159278/used/12345")
        assert info is not None
        assert info["status"] == "UNKNOWN"
        assert info["skus"][0]["in_stock"] is None   # ★ 判定不能 (False ではない)

    def test_rsc_is_sold_out_true(self):
        """RSC ペイロード isSoldOut:true (当該id同一object) → SOLD_OUT."""
        html = ('<html><script>self.__next_f.push([1,"...'
                '{\\"id\\":12345,\\"isUsed\\":true,\\"isSoldOut\\":true,\\"price\\":8900}'
                '..."])</script></html>').replace("\\", "")
        with patch("scrapers.snkrdunk_scraper.requests.get",
                   return_value=_mock_response(200, html)):
            info = fetch_product_inventory(
                "https://snkrdunk.com/apparels/159278/used/12345")
        assert info["status"] == "SOLD_OUT"
        assert info["skus"][0]["in_stock"] is False

    def test_rsc_is_sold_out_false(self):
        """RSC isSoldOut:false → IN_STOCK (WebFetch=販売中 と一致する側)."""
        html = '<html><script>x={"id":12345,"isSoldOut":false,"isUsed":true}</script></html>'
        with patch("scrapers.snkrdunk_scraper.requests.get",
                   return_value=_mock_response(200, html)):
            info = fetch_product_inventory(
                "https://snkrdunk.com/apparels/159278/used/12345")
        assert info["status"] == "IN_STOCK"
        assert info["skus"][0]["in_stock"] is True

    def test_rsc_other_item_not_attributed(self):
        """別 item(別id)の isSoldOut を当該 id に誤帰属しない (同一object境界を守る)。"""
        # id=99999 が sold、当該 id=12345 の isSoldOut は無い → 当該は判定不能
        html = '<html><script>a={"id":99999,"isSoldOut":true};b={"id":12345,"name":"x"}</script></html>'
        with patch("scrapers.snkrdunk_scraper.requests.get",
                   return_value=_mock_response(200, html)):
            info = fetch_product_inventory(
                "https://snkrdunk.com/apparels/159278/used/12345")
        assert info["status"] == "UNKNOWN"
        assert info["skus"][0]["in_stock"] is None

    def test_monitor_treats_none_as_uncertain(self):
        """結合: snkrdunk in_stock=None → monitor _check_single_url が is_sold=None(uncertain)+error."""
        import monitor_listings as ml
        with patch("scrapers.snkrdunk_scraper.requests.get",
                   return_value=_mock_response(200, "<html>csr no signal</html>")):
            sub = ml._check_single_url("https://snkrdunk.com/apparels/159278/used/12345")
        assert sub["is_sold"] is None       # ★ 偽 sold(True) にならない
        assert sub["error"] is not None     # uncertain = error 明示 → 要手動chk へ

    def test_network_error(self):
        # _no_api autouse で listing_live_price=(None,None) → requests 経路 → ConnectionError → None
        with patch("scrapers.snkrdunk_scraper.requests.get",
                   side_effect=ConnectionError("network down")):
            info = fetch_product_inventory(
                "https://snkrdunk.com/apparels/159278/used/45538280")
        assert info is None   # 通信失敗 = None で呼出側に判断委ねる


class TestApiListingLive:
    """★ 2026-07-25 API 復旧 + 2026-07-26 価格付き: HQ listing_live_price を PRIMARY 判定に統合。"""

    def test_live_true_with_price_for_min(self):
        """★(True, 9000) → IN_STOCK + price_jpy=9000 (= M-min に snkrdunk 価格が効く)."""
        with patch("scrapers.snkrdunk_scraper._hq_listing_live_price", return_value=(True, 9000)):
            info = fetch_product_inventory(
                "https://snkrdunk.com/apparels/157939/used/47480716")
        assert info["status"] == "IN_STOCK"
        assert info["skus"][0]["in_stock"] is True
        assert info["skus"][0]["price_jpy"] == 9000

    def test_live_true_price_none_excluded_from_min(self):
        """(True, None) = live だが価格未確定 → in_stock=True だが price_jpy=None (M-min対象外)."""
        with patch("scrapers.snkrdunk_scraper._hq_listing_live_price", return_value=(True, None)):
            info = fetch_product_inventory(
                "https://snkrdunk.com/apparels/157939/used/47480716")
        assert info["status"] == "IN_STOCK"
        assert info["skus"][0]["in_stock"] is True
        assert info["skus"][0]["price_jpy"] is None

    def test_live_false_sold_out(self):
        """listing_id が一覧に無い = 売切 → SOLD_OUT (= 消込を snkrdunk でも正しく発火)."""
        with patch("scrapers.snkrdunk_scraper._hq_listing_live_price", return_value=(False, None)):
            info = fetch_product_inventory(
                "https://snkrdunk.com/apparels/742110/used/46890058")
        assert info["status"] == "SOLD_OUT"
        assert info["skus"][0]["in_stock"] is False

    def test_live_none_falls_back_to_requests_404(self):
        """helper が (None,None)(API失敗/非対象) → 従来 requests 経路へ。404 は依然 sold として拾う."""
        with patch("scrapers.snkrdunk_scraper._hq_listing_live_price", return_value=(None, None)), \
             patch("scrapers.snkrdunk_scraper.requests.get",
                   return_value=_mock_response(404, "")):
            info = fetch_product_inventory(
                "https://snkrdunk.com/apparels/159278/used/12345")
        assert info["status"] == "DELETED"
        assert info["skus"][0]["in_stock"] is False

    def test_live_none_and_csr_page_is_uncertain(self):
        """helper (None,None) + CSR ページ(信号なし) → UNKNOWN/in_stock=None (偽sold にしない fail-closed)."""
        with patch("scrapers.snkrdunk_scraper._hq_listing_live_price", return_value=(None, None)), \
             patch("scrapers.snkrdunk_scraper.requests.get",
                   return_value=_mock_response(200, "<html>csr no signal</html>")):
            info = fetch_product_inventory(
                "https://snkrdunk.com/apparels/159278/used/12345")
        assert info["status"] == "UNKNOWN"
        assert info["skus"][0]["in_stock"] is None

    def test_helper_import_failure_safe_fallback(self):
        """helper が例外 → (None,None) 扱いで既存経路へ (import 事故でも crash しない)."""
        import scrapers.snkrdunk_scraper as sd
        sd._LIVE_CACHE.clear()
        sd._LIVE_PRICE_CACHE.clear()
        with patch("scrapers.snkrdunk_scraper.sys.path", []), \
             patch("scrapers.snkrdunk_scraper.requests.get",
                   return_value=_mock_response(404, "")):
            # _hq_listing_live_price は import 失敗 → (None,None) → 404 経路
            info = fetch_product_inventory(
                "https://snkrdunk.com/apparels/159278/used/12345")
        assert info["status"] == "DELETED"


# ============================================================================
# supplier detection 結合
# ============================================================================
def test_detect_supplier_snkrdunk():
    from sheet_updater import _domain_of, detect_supplier
    url = "https://snkrdunk.com/apparels/159278/used/45538280"
    assert detect_supplier(_domain_of(url)) == "snkrdunk"


def test_detect_supplier_snkrdunk_no_protocol():
    """protocol 抜けでも snkrdunk 判定."""
    from sheet_updater import _domain_of, detect_supplier
    url = "snkrdunk.com/apparels/159278/used/45538280"
    assert detect_supplier(_domain_of(url)) == "snkrdunk"
