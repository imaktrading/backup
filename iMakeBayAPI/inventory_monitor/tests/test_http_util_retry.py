"""_http_util.get_with_retry の transient retry regression (2026-06-19).

公式 monitor の supplier API (uniqlo/gu) が cycle 時刻の DNS blip (getaddrinfo failed) で
1 listing scrape error → ⚠️ noise になる頻発事象の対策。 transient(DNS/接続)のみ backoff
retry し、 数秒の blip を吸収する。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import requests

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import _http_util as H  # noqa: E402


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(H, "_BACKOFFS", (0, 0, 0))


def test_transient_dns_then_success(monkeypatch):
    calls = {"n": 0}
    sentinel = object()

    def fake_get(url, headers=None, timeout=25):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise requests.exceptions.ConnectionError(
                "HTTPSConnectionPool: Failed to resolve 'www.uniqlo.com' (getaddrinfo failed)")
        return sentinel

    monkeypatch.setattr(H.requests, "get", fake_get)
    assert H.get_with_retry("http://x") is sentinel
    assert calls["n"] == 3


def test_non_transient_raises_immediately(monkeypatch):
    calls = {"n": 0}

    def fake_get(url, headers=None, timeout=25):
        calls["n"] += 1
        raise ValueError("not a network error")

    monkeypatch.setattr(H.requests, "get", fake_get)
    with pytest.raises(ValueError):
        H.get_with_retry("http://x")
    assert calls["n"] == 1


def test_persistent_transient_raises_after_max(monkeypatch):
    calls = {"n": 0}

    def fake_get(url, headers=None, timeout=25):
        calls["n"] += 1
        raise requests.exceptions.ConnectionError("getaddrinfo failed")

    monkeypatch.setattr(H.requests, "get", fake_get)
    with pytest.raises(requests.exceptions.ConnectionError):
        H.get_with_retry("http://x")
    assert calls["n"] == len(H._BACKOFFS)
