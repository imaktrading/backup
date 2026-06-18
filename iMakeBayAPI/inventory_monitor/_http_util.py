"""_http_util - transient (DNS/接続) 失敗に強い requests.get wrapper.

公式 monitor の supplier API 呼出 (uniqlo / gu の L2S/details API 等) で、
sheets/uniqlo/gu の `getaddrinfo failed` (一時的 DNS 解決失敗) が cycle 時刻に頻発
(2026-06 の 2 日で 3 回: sheets.googleapis.com / gu-global.com / uniqlo.com)。
素の requests.get は urllib3 の即時 retry のみで数秒の DNS blip を救えず、 1 listing が
scrape error → ⚠️ 要対応 メール noise になる (実害は fail-closed + 次 cycle 自己回復で無し)。

backoff retry で数秒の blip を吸収する (= sheet_updater.open_sheet の retry と同思想)。
transient のみ retry、 それ以外 (4xx/5xx は raise_for_status 側、 JSON エラー等) は即送出。
"""
from __future__ import annotations

import time

import requests

_TRANSIENT_KEYWORDS = (
    "getaddrinfo failed", "NameResolutionError", "Failed to resolve",
    "Max retries exceeded", "Connection aborted", "RemoteDisconnected",
    "Temporary failure in name resolution",
)
# listing 単位で呼ばれる (74 listing) ので短め。 blip は数秒で復帰する想定 (計 ~12s)。
_BACKOFFS = (0, 3, 9)


def _is_transient(exc: Exception) -> bool:
    if isinstance(exc, (requests.exceptions.ConnectionError, requests.exceptions.Timeout)):
        return True
    msg = f"{type(exc).__name__}: {exc}"
    return any(k in msg for k in _TRANSIENT_KEYWORDS)


def get_with_retry(url, headers=None, timeout=25):
    """requests.get の transient(DNS/接続) backoff retry 版.

    transient な接続/DNS 失敗は短い backoff で retry、 それ以外は即 raise、
    全 attempt 失敗時は最後の例外を送出 (= 呼出側で従来通り fail-closed)。
    """
    last = None
    for attempt, backoff in enumerate(_BACKOFFS, start=1):
        if backoff:
            time.sleep(backoff)
        try:
            return requests.get(url, headers=headers, timeout=timeout)
        except Exception as e:  # noqa: BLE001
            last = e
            if not _is_transient(e) or attempt >= len(_BACKOFFS):
                raise
    raise last  # 到達しない (ループ内で return/raise)
