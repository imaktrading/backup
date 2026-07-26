"""snkrdunk scraper の接続例外リトライ (fetch_product_inventory) offline テスト.

2026-06-11: cycle 中の snkrdunk が rate-limit/接続瞬断で 1 候補だけ requests 例外
→ http_status=None → None → monitor 側で「uncertain: N/M candidates errored」誤アラート。
落ちた候補が唯一の在庫ありだと「在庫あるのに uncertain」になる。 fril と同型の retry を追加。
"""
import pytest

import scrapers.snkrdunk_scraper as s

pytestmark = pytest.mark.offline


@pytest.fixture(autouse=True)
def _no_api(monkeypatch):
    # ★ 2026-07-26: listing_live_price(PRIMARY) を uncertain 固定 → 従来 requests retry 経路を検証。
    monkeypatch.setattr(s, "_hq_listing_live_price", lambda url: (None, None))


def test_retry_recovers_on_transient_conn_error(monkeypatch):
    monkeypatch.setattr(s.time, "sleep", lambda x: None)
    calls = {"n": 0}

    def fake(url):
        calls["n"] += 1
        if calls["n"] < 3:                                   # 2 回 接続失敗を模擬
            return {"http_status": None, "in_stock": False, "name": "", "price_jpy": None,
                    "_reason": "http_error:ConnectionError"}
        return {"http_status": 200, "in_stock": True, "name": "PSA10 X",
                "price_jpy": 35000, "_reason": "instock"}

    monkeypatch.setattr(s, "_fetch_via_requests", fake)
    r = s.fetch_product_inventory("https://snkrdunk.com/apparels/1/used/2")
    assert calls["n"] == 3                                   # 3 回目で確定 = retry した
    assert r and r["status"] == "IN_STOCK"
    assert r["skus"][0]["in_stock"] is True


def test_retry_exhausted_returns_none(monkeypatch):
    monkeypatch.setattr(s.time, "sleep", lambda x: None)
    calls = {"n": 0}

    def always_conn_err(url):
        calls["n"] += 1
        return {"http_status": None, "in_stock": False, "name": "", "price_jpy": None,
                "_reason": "http_error:Timeout"}

    monkeypatch.setattr(s, "_fetch_via_requests", always_conn_err)
    r = s.fetch_product_inventory("https://snkrdunk.com/apparels/1/used/2", max_retries=3)
    assert calls["n"] == 4                                   # 初回 + retry 3 = 4
    assert r is None                                         # 全滅は None


def test_definitive_404_no_retry(monkeypatch):
    """404 (= http_status 立つ) は確定なので retry しない."""
    monkeypatch.setattr(s.time, "sleep", lambda x: None)
    calls = {"n": 0}

    def deleted(url):
        calls["n"] += 1
        return {"http_status": 404, "in_stock": False, "name": "", "price_jpy": None,
                "_reason": "http_404"}

    monkeypatch.setattr(s, "_fetch_via_requests", deleted)
    r = s.fetch_product_inventory("https://snkrdunk.com/apparels/1/used/2")
    assert calls["n"] == 1                                   # 1 回で確定
    assert r and r["status"] == "DELETED"
