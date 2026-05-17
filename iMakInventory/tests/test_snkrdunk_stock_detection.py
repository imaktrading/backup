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

    def test_jsonld_missing(self):
        with patch("scrapers.snkrdunk_scraper.requests.get",
                   return_value=_mock_response(200, "<html>no jsonld</html>")):
            info = fetch_product_inventory(
                "https://snkrdunk.com/apparels/159278/used/12345")
        assert info is not None
        assert info["status"] == "UNKNOWN"
        assert info["skus"][0]["in_stock"] is False   # fail-closed

    def test_network_error(self):
        with patch("scrapers.snkrdunk_scraper.requests.get",
                   side_effect=ConnectionError("network down")):
            info = fetch_product_inventory(
                "https://snkrdunk.com/apparels/159278/used/45538280")
        assert info is None   # 通信失敗 = None で呼出側に判断委ねる


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
