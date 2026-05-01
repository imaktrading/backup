"""Regression: dns_resilience の自動 retry + flush 挙動 (2026-05-01 18:17 事故対応).

事故: psa_to_csv の eBay token 取得段階で getaddrinfo failed → 全 19 行 $100 fallback.
対策: dns_resilience.with_dns_retry が getaddrinfo 失敗を検出して
     ipconfig /flushdns + 1 回 retry を自動実行.

本テストは:
  1. flush_dns_cache のプラットフォーム別動作 (no-op vs subprocess)
  2. _is_dns_resolution_error の判定精度 (gaierror / wrap 例外文字列)
  3. with_dns_retry の自動 retry 挙動 (失敗→flush→成功 / 完全失敗 / 非DNS例外即raise)
"""
from __future__ import annotations
import socket
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_EBAY_API = _REPO_ROOT / "iMakeBayAPI"
if str(_EBAY_API) not in sys.path:
    sys.path.insert(0, str(_EBAY_API))


# ============================================================================
# flush_dns_cache
# ============================================================================
def test_flush_dns_cache_returns_bool():
    """戻り値は常に bool. 例外は内部で吸収."""
    from dns_resilience import flush_dns_cache
    result = flush_dns_cache()
    assert isinstance(result, bool)


def test_flush_dns_cache_non_windows_skipped():
    """非 Windows なら no-op で False (subprocess 呼ばない)."""
    from dns_resilience import flush_dns_cache
    with patch("sys.platform", "linux"):
        with patch("subprocess.run") as mock_run:
            assert flush_dns_cache() is False
            mock_run.assert_not_called()


def test_flush_dns_cache_windows_calls_ipconfig():
    """Windows なら ipconfig /flushdns を呼ぶ."""
    from dns_resilience import flush_dns_cache
    with patch("sys.platform", "win32"):
        with patch("dns_resilience.subprocess.run") as mock_run:
            flush_dns_cache()
            mock_run.assert_called_once()
            args = mock_run.call_args.args[0]
            assert args == ["ipconfig", "/flushdns"]


# ============================================================================
# _is_dns_resolution_error
# ============================================================================
def test_is_dns_resolution_error_socket_gaierror():
    """socket.gaierror は True."""
    from dns_resilience import _is_dns_resolution_error
    assert _is_dns_resolution_error(socket.gaierror(11001, "getaddrinfo failed")) is True


def test_is_dns_resolution_error_wrapped_exception():
    """getaddrinfo failed 文字列を含む wrap 例外も True."""
    from dns_resilience import _is_dns_resolution_error
    e = ConnectionError("HTTPSConnectionPool ... NameResolutionError: getaddrinfo failed")
    assert _is_dns_resolution_error(e) is True


def test_is_dns_resolution_error_unrelated():
    """HTTP エラーや TimeoutError は False (DNS と無関係)."""
    from dns_resilience import _is_dns_resolution_error
    assert _is_dns_resolution_error(TimeoutError("timeout")) is False
    assert _is_dns_resolution_error(ValueError("bad request")) is False
    assert _is_dns_resolution_error(RuntimeError("server returned 500")) is False


def test_is_dns_resolution_error_chained_exception():
    """例外チェーンの深い位置に getaddrinfo failed があっても検出."""
    from dns_resilience import _is_dns_resolution_error
    inner = socket.gaierror(11001, "getaddrinfo failed")
    middle = ConnectionError("connection error")
    middle.__cause__ = inner
    outer = RuntimeError("outer wrapper")
    outer.__cause__ = middle
    assert _is_dns_resolution_error(outer) is True


# ============================================================================
# with_dns_retry
# ============================================================================
def test_with_dns_retry_success_first_try():
    """成功すれば retry 不要、flush も呼ばない."""
    from dns_resilience import with_dns_retry
    calls = {"count": 0}
    def fn():
        calls["count"] += 1
        return "ok"
    with patch("dns_resilience.flush_dns_cache") as mock_flush:
        result = with_dns_retry(fn)
        assert result == "ok"
        assert calls["count"] == 1
        mock_flush.assert_not_called()


def test_with_dns_retry_dns_failure_then_success():
    """DNS 失敗 → flush + retry → 2 回目で成功."""
    from dns_resilience import with_dns_retry
    calls = {"count": 0}
    def fn():
        calls["count"] += 1
        if calls["count"] == 1:
            raise socket.gaierror(11001, "getaddrinfo failed")
        return "recovered"
    with patch("dns_resilience.flush_dns_cache", return_value=True) as mock_flush:
        result = with_dns_retry(fn, max_retries=1)
        assert result == "recovered"
        assert calls["count"] == 2
        mock_flush.assert_called_once()


def test_with_dns_retry_dns_failure_persistent():
    """DNS が retry でも復活しなければ最終的に raise."""
    from dns_resilience import with_dns_retry
    def fn():
        raise socket.gaierror(11001, "getaddrinfo failed")
    with patch("dns_resilience.flush_dns_cache", return_value=True):
        with pytest.raises(socket.gaierror):
            with_dns_retry(fn, max_retries=1)


def test_with_dns_retry_non_dns_error_immediate_raise():
    """DNS 以外の例外は retry せず即 raise (flush も呼ばない)."""
    from dns_resilience import with_dns_retry
    def fn():
        raise ValueError("non-DNS error")
    with patch("dns_resilience.flush_dns_cache") as mock_flush:
        with pytest.raises(ValueError):
            with_dns_retry(fn, max_retries=3)
        mock_flush.assert_not_called()


def test_with_dns_retry_passes_args_kwargs():
    """args / kwargs が透過的に func に渡る."""
    from dns_resilience import with_dns_retry
    def fn(a, b, c=None):
        return (a, b, c)
    assert with_dns_retry(fn, 1, 2, c=3) == (1, 2, 3)
