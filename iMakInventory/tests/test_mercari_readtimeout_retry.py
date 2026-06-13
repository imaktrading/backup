"""mercari scraper の ReadTimeout 再取得リトライ offline テスト.

2026-06-14: 特定の重い mercari ページで driver コマンドが ReadTimeout を間欠的に出す
(row729 等)。「エラー除外」は売切を silent 見逃す fail-OPEN なので禁止。 代わりに同 row を
再取得 (retry) して transient を吸収する。 読めれば確定、 読めなければ依然 error (=漏れにしない)。
"""
import pytest

import scrapers.mercari_scraper as m

pytestmark = pytest.mark.offline


def test_readtimeout_retry_recovers(monkeypatch):
    monkeypatch.setattr(m.time, "sleep", lambda x: None)
    monkeypatch.setattr(m, "_check_404", lambda u: False)
    calls = {"n": 0}

    def fake(driver, url, is_shops):
        calls["n"] += 1
        if calls["n"] < 3:
            raise Exception("ReadTimeoutError: HTTPConnectionPool(host='localhost') Read timed out")
        return {"name": "X", "in_stock": True, "price_jpy": 1500, "status": "ON_SALE"}

    monkeypatch.setattr(m, "_detect_via_selenium", fake)
    r = m.fetch_product_inventory("https://jp.mercari.com/item/mXXX", driver=object())
    assert calls["n"] == 3                       # 2 回 ReadTimeout → 3 回目で確定
    assert r and r["status"] == "ON_SALE"
    assert r["skus"][0]["in_stock"] is True


def test_readtimeout_exhausted_raises(monkeypatch):
    """retry 尽きたら raise (呼出元で error 化 = 漏れにしない、 除外しない)."""
    monkeypatch.setattr(m.time, "sleep", lambda x: None)
    monkeypatch.setattr(m, "_check_404", lambda u: False)

    def always_timeout(driver, url, is_shops):
        raise Exception("ReadTimeoutError: Read timed out")

    monkeypatch.setattr(m, "_detect_via_selenium", always_timeout)
    with pytest.raises(Exception):
        m.fetch_product_inventory("https://jp.mercari.com/item/mXXX", driver=object(), max_retries=2)


def test_non_transient_not_retried(monkeypatch):
    """transient でない例外 (= 構造変更等) は retry せず即 raise."""
    monkeypatch.setattr(m.time, "sleep", lambda x: None)
    monkeypatch.setattr(m, "_check_404", lambda u: False)
    calls = {"n": 0}

    def value_err(driver, url, is_shops):
        calls["n"] += 1
        raise ValueError("unexpected DOM structure")

    monkeypatch.setattr(m, "_detect_via_selenium", value_err)
    with pytest.raises(ValueError):
        m.fetch_product_inventory("https://jp.mercari.com/item/mXXX", driver=object())
    assert calls["n"] == 1                       # 非 transient は 1 回で諦め (retry しない)
