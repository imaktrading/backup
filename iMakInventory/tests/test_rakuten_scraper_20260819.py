"""楽天 (カプセルトイ) 在庫判定の test — 2026-08-19 HQ 依頼の実装.

守る性質:
  1. **3点一致でだけ売切を確定する** (availability / soldout / quantity)。
     1本でも割れたら判定不能 = 触らない。単独 signal に寄せると、楽天の画面改修で
     静かに「全部売切」へ倒れて誤取下げを量産する (2026-06-03 偽OOS 95件と同型)。
  2. **判定不能を False (売切) に潰さない**。in_stock は 3値のまま返す。
  3. **予約品を売切扱いしない**。在庫ありでも発送できないので気づく口だけ残す。

検体は実ページから判定に使う marker だけ抜いて保存 (tests/fixtures/rakuten/)。
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scrapers import rakuten_scraper as rk  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "rakuten"
SOLD = (FIXTURES / "sold_g73619.html").read_text(encoding="utf-8")
IN_STOCK = (FIXTURES / "in_stock_g73620.html").read_text(encoding="utf-8")
PREORDER = (FIXTURES / "preorder_g20070zs01t.html").read_text(encoding="utf-8")


# ============================================================================
# 3点一致
# ============================================================================
def test_real_sold_page_is_sold():
    in_stock, reason = rk.detect_stock(SOLD)
    assert in_stock is False
    assert reason == "sold_3signals"


def test_real_in_stock_page_is_in_stock():
    in_stock, reason = rk.detect_stock(IN_STOCK)
    assert in_stock is True
    assert "in_stock_3signals" in reason


@pytest.mark.parametrize("html,why", [
    ('itemprop="availability" content="http://schema.org/OutOfStock"'
     '\n"soldout":0\n"quantity":5', "availability だけ売切"),
    ('itemprop="availability" content="http://schema.org/InStock"'
     '\n"soldout":1\n"quantity":5', "soldout だけ売切"),
    ('itemprop="availability" content="http://schema.org/InStock"'
     '\n"soldout":0\n"quantity":0', "在庫数だけ 0"),
])
def test_disagreement_is_indeterminate_not_sold(html, why):
    """★ 割れたら売切にしない。ここが誤取下げを止める線."""
    in_stock, reason = rk.detect_stock(html)

    assert in_stock is None, f"{why} で売切に倒れた"
    assert "disagree" in reason


@pytest.mark.parametrize("html", [
    "",                                             # 空 (取得失敗の残骸)
    '"soldout":0\n"quantity":5',                    # availability 欠落
    'itemprop="availability" content="InStock"\n"quantity":5',   # soldout 欠落
    'itemprop="availability" content="InStock"\n"soldout":0',    # quantity 欠落
])
def test_missing_marker_is_indeterminate(html):
    """楽天が marker 名を変えたら「全部売切」ではなく「判定不能」に倒れること."""
    in_stock, _ = rk.detect_stock(html)
    assert in_stock is None


# ============================================================================
# 予約 (在庫ありでも発送できない)
# ============================================================================
def test_preorder_page_is_in_stock_but_flagged():
    """予約品は売切ではない (取下げない)。ただし予約と分かること."""
    in_stock, _ = rk.detect_stock(PREORDER)
    is_pre, msg = rk.detect_preorder(PREORDER)

    assert in_stock is True      # 売切ではない
    assert is_pre is True
    assert "発売予定" in msg


def test_immediate_shipping_is_not_preorder():
    is_pre, msg = rk.detect_preorder(IN_STOCK)
    assert is_pre is False
    assert msg


def test_no_delivery_message_is_unknown_preorder():
    """配送メッセージが無ければ「予約ではない」と決めつけない."""
    is_pre, msg = rk.detect_preorder('"soldout":0')
    assert is_pre is None
    assert msg == ""


# ============================================================================
# fetch_product_inventory (契約)
# ============================================================================
def _fake_response(status_code=200, text=""):
    class R:
        pass
    r = R()
    r.status_code = status_code
    r.text = text
    return r


def test_404_is_deleted():
    with patch.object(rk.requests, "get", return_value=_fake_response(404)):
        info = rk.fetch_product_inventory("https://item.rakuten.co.jp/shop/item1/")

    assert info["status"] == "DELETED"
    assert info["skus"][0]["in_stock"] is False


def test_indeterminate_returns_unknown_with_none_in_stock():
    """★ 判定不能は UNKNOWN + in_stock=None (False に潰さない)."""
    with patch.object(rk.requests, "get", return_value=_fake_response(200, "<html>変更後</html>")):
        info = rk.fetch_product_inventory("https://item.rakuten.co.jp/shop/item1/")

    assert info["status"] == "UNKNOWN"
    assert info["skus"][0]["in_stock"] is None


def test_connection_failure_returns_none():
    """通信失敗は None (= 呼出側で「判定不能」扱い)。retry しても駄目な場合."""
    with patch.object(rk.requests, "get", side_effect=rk.requests.RequestException("boom")), \
         patch.object(rk.time, "sleep"):
        assert rk.fetch_product_inventory("https://item.rakuten.co.jp/shop/item1/") is None


def test_in_stock_contract_fields():
    with patch.object(rk.requests, "get", return_value=_fake_response(200, IN_STOCK)):
        info = rk.fetch_product_inventory("https://item.rakuten.co.jp/kidsroom/g73620/")

    assert info["status"] == "IN_STOCK"
    assert info["product_id"] == "kidsroom:g73620"
    sku = info["skus"][0]
    assert sku["in_stock"] is True
    assert isinstance(sku["price_jpy"], int)
    assert info["is_preorder"] is False


def test_parse_product_id():
    assert rk.parse_product_id("https://item.rakuten.co.jp/kidsroom/g73620/") == "kidsroom:g73620"
    assert rk.parse_product_id("https://www.rakuten.co.jp/kidsroom/") is None


# ============================================================================
# 巡回への組込み
# ============================================================================
def test_supplier_detection():
    from sheet_updater import detect_supplier  # noqa: PLC0415

    assert detect_supplier("item.rakuten.co.jp") == "rakuten"
    # 楽天ブックス等は未対応のまま (= 判定不能に倒れる。勝手に取下げない)
    assert detect_supplier("books.rakuten.co.jp") == "other"


def test_check_single_url_marks_preorder():
    """巡回の per-URL 判定で、予約は「在庫あり + 予約フラグ」になること (売切にしない)."""
    import monitor_listings as ml  # noqa: PLC0415

    info = {"status": "IN_STOCK", "is_preorder": True, "delivery_message": "2026年10月下旬発売予定",
            "skus": [{"in_stock": True, "price_jpy": 1750}]}
    with patch.object(ml, "fetch_rakuten", return_value=info), patch.object(ml, "log"):
        sub = ml._check_single_url("https://item.rakuten.co.jp/auc-yuyou/g20070zs01t/", sleep_sec=0)

    assert sub["is_sold"] is False        # 取下げ対象にしない
    assert sub["preorder"] is True        # だが気づける
    assert "予約" in sub["raw_status"]


def test_check_single_url_indeterminate_does_not_mark_sold():
    import monitor_listings as ml  # noqa: PLC0415

    info = {"status": "UNKNOWN", "is_preorder": None, "delivery_message": "",
            "skus": [{"in_stock": None, "price_jpy": None}]}
    with patch.object(ml, "fetch_rakuten", return_value=info):
        sub = ml._check_single_url("https://item.rakuten.co.jp/shop/x/", sleep_sec=0)

    assert sub["is_sold"] is None
    assert sub["error"]
