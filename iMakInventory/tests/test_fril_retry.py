"""fril scraper の no_signal リトライ (fetch_product_inventory) offline テスト.

2026-06-11: cycle 中の fril が負荷で marker 無しページを間欠返し → _detect_stock が
no_signal=None → 同一行(row542等)が 1日数回「scraper returned None」を繰返す事故。
単独 re-fetch では正常判定できるため、 no_signal 時に再 fetch する retry を追加した。
"""
import pytest

import scrapers.fril_scraper as f

pytestmark = pytest.mark.offline


def test_retry_recovers_on_transient_none(monkeypatch):
    monkeypatch.setattr(f.time, "sleep", lambda s: None)  # backoff 無効化
    calls = {"n": 0}

    def fake(url):
        calls["n"] += 1
        if calls["n"] < 3:        # 2 回 no_signal を模擬
            return None
        return {"name": "x", "in_stock": True, "price_jpy": 2100, "_reason": "buy_button"}

    monkeypatch.setattr(f, "_fetch_via_requests", fake)
    r = f.fetch_product_inventory("https://item.fril.jp/xxx")
    assert calls["n"] == 3                       # 3 回目で確定 = retry した
    assert r and r["status"] == "IN_STOCK"
    assert r["skus"][0]["in_stock"] is True


def test_retry_exhausted_returns_none_failclosed(monkeypatch):
    monkeypatch.setattr(f.time, "sleep", lambda s: None)
    calls = {"n": 0}

    def always_none(url):
        calls["n"] += 1
        return None

    monkeypatch.setattr(f, "_fetch_via_requests", always_none)
    r = f.fetch_product_inventory("https://item.fril.jp/xxx", max_retries=2)
    assert calls["n"] == 3                        # max_retries=2 → 計 3 回試行
    assert r is None                              # 全滅は None (fail-closed 維持)


def test_definitive_result_no_retry(monkeypatch):
    """404/sold/in_stock の確定 dict は即 break (retry しない)."""
    monkeypatch.setattr(f.time, "sleep", lambda s: None)
    calls = {"n": 0}

    def deleted(url):
        calls["n"] += 1
        return {"name": "(deleted)", "in_stock": False, "price_jpy": None, "_reason": "http_404"}

    monkeypatch.setattr(f, "_fetch_via_requests", deleted)
    r = f.fetch_product_inventory("https://item.fril.jp/xxx")
    assert calls["n"] == 1                        # 1 回で確定 = retry しない
    assert r and r["status"] == "DELETED"
