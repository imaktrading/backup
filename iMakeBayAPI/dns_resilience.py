"""dns_resilience - getaddrinfo 失敗時の自動 DNS flush + retry wrapper.

設計目的:
  Windows 環境で eBay API 呼出中に発生する `getaddrinfo failed` エラーの
  大半 (= ローカル DNS resolver cache 詰まり) を、ユーザー介在ゼロで自動回復させる.

  典型シナリオ (2026-05-01 18:17 事故):
    - eBay token 取得 1 発目で getaddrinfo failed → 全 19 行 $100 fallback
    - 手動で `ipconfig /flushdns` 実行 → 再走で正常稼働
    - → 自動化すれば手動再走不要

設計原則 (修正連鎖回避):
  - 既存モジュール (market_gate / check_csv_core) を一切修正しない (call site で wrap するだけ)
  - 失敗時は元例外をそのまま re-raise (= 既存 fallback 動作を保持)
  - Windows 以外 (Linux/macOS) は flush no-op、副作用ゼロ

使用例:
    from dns_resilience import with_dns_retry
    resp = with_dns_retry(requests.get, url, headers=headers, timeout=15)
    # → getaddrinfo failed 時に flush + 1 回 retry. 成功なら resp、失敗なら元例外.

CLI:
    python dns_resilience.py test    # api.ebay.com 解決テスト + flush 動作確認
"""
from __future__ import annotations

import socket
import subprocess
import sys
from typing import Callable


# ============================================================================
# DNS cache flush
# ============================================================================
def flush_dns_cache() -> bool:
    """Windows DNS resolver cache を flush. Windows 以外は no-op で False 返却.

    Returns:
        True: flush 成功, False: スキップ (非 Windows or subprocess 失敗)
    """
    if sys.platform != "win32":
        return False
    try:
        subprocess.run(
            ["ipconfig", "/flushdns"],
            capture_output=True,
            timeout=5,
            check=False,
        )
        return True
    except Exception as e:
        print(f"  ⚠️ dns_resilience: flushdns 例外 {type(e).__name__}: {e}")
        return False


# ============================================================================
# DNS resolution failure 検出
# ============================================================================
def _is_dns_resolution_error(exc: BaseException) -> bool:
    """例外が DNS 解決失敗を示すか判定.

    socket.gaierror (= getaddrinfo failed) およびそれを wrap している
    urllib3 NameResolutionError / requests ConnectionError 全てに対応.
    """
    # 直接 socket.gaierror
    if isinstance(exc, socket.gaierror):
        return True
    # 文字列マッチ (例外チェーン全段スキャン)
    cur: BaseException | None = exc
    while cur is not None:
        msg = str(cur).lower()
        if "getaddrinfo failed" in msg or "nameresolutionerror" in msg:
            return True
        if "name or service not known" in msg:  # Linux 風メッセージも一応カバー
            return True
        cur = cur.__cause__ or cur.__context__
    return False


# ============================================================================
# Retry wrapper (公開 API)
# ============================================================================
def with_dns_retry(func: Callable, *args, max_retries: int = 1, **kwargs):
    """func(*args, **kwargs) を実行. DNS 解決失敗なら flush + retry.

    Args:
        func: 呼び出す関数 (requests.get / requests.post 等)
        *args, **kwargs: func に渡す引数
        max_retries: DNS 失敗時の追加 retry 回数 (default=1).
                     0 にすると wrap 効果ゼロ (透過). 大きくしすぎると無限ループ気味.

    Returns:
        func の戻り値 (成功時)

    Raises:
        最後の試行で発生した例外 (DNS 関連かどうか問わず). DNS 関連なら flush 済み.
    """
    last_exc: BaseException | None = None
    for attempt in range(max_retries + 1):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            last_exc = e
            if not _is_dns_resolution_error(e):
                # DNS 以外の例外 (HTTP 5xx 等) は retry せず即 raise
                raise
            if attempt < max_retries:
                print(
                    f"  ⚠️ dns_resilience: getaddrinfo 失敗検出 → "
                    f"flushdns 実行 (attempt {attempt+1}/{max_retries})"
                )
                flush_dns_cache()
                continue
            # 全 retry 消尽 → 元例外 raise
            raise
    # ここには到達しないが型整合のため
    assert last_exc is not None
    raise last_exc


# ============================================================================
# CLI (動作確認用)
# ============================================================================
def _selftest() -> int:
    """api.ebay.com に対する DNS 解決テスト + flush 動作確認."""
    print("=== dns_resilience selftest ===")
    print(f"  platform: {sys.platform}")
    # 1. flush 試行 (副作用確認)
    print(f"  flush_dns_cache(): {flush_dns_cache()}")
    # 2. socket.getaddrinfo 試行
    target = "api.ebay.com"
    try:
        infos = socket.getaddrinfo(target, 443)
        print(f"  ✓ {target} 解決 OK: {len(infos)} record(s), 例: {infos[0][4]}")
        return 0
    except socket.gaierror as e:
        print(f"  ✗ {target} 解決失敗: {e}")
        return 1
    except Exception as e:
        print(f"  ⚠️ 想定外例外: {type(e).__name__}: {e}")
        return 2


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        sys.exit(_selftest())
    print(__doc__)
