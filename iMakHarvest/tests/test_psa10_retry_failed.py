"""tests/test_psa10_retry_failed - 未判定 (取得できなかった) 分の拾い直し.

2026-08-18: 取得失敗は件数しか残していなかったため、 後から URL を特定できなかった
(ポケモン92件 + ワンピース42件)。 以後は `failed_urls` に URL を残し、
`--retry-from-json` で 成果物にならなかった URL だけ拾い直す。
"""
from __future__ import annotations

import pytest

from run_harvest_mercari_psa10 import retry_urls_from

pytestmark = pytest.mark.offline

U = "https://jp.mercari.com/item/m%d"


def _payload():
    return {
        "processed_urls": [U % i for i in range(1, 6)],
        "candidates": [{"url": U % 1}],
        "unreadable": [{"url": U % 2}],
    }


def test_retry_targets_are_processed_minus_results():
    assert retry_urls_from(_payload()) == [U % 3, U % 4, U % 5]


def test_already_in_staging_is_excluded():
    """中間スプシに入っている URL は拾い直さない (Vision 課金と時間の無駄)."""
    got = retry_urls_from(_payload(), exclude={"m3", "m4"})
    assert got == [U % 5]


def test_empty_payload_is_safe():
    assert retry_urls_from({}) == []
    assert retry_urls_from({"processed_urls": []}) == []


def test_failed_urls_key_is_kept_for_resume():
    """failed_urls を持つ payload でも 拾い直し対象の計算は変わらない."""
    p = _payload()
    p["failed_urls"] = [U % 3]
    assert retry_urls_from(p) == [U % 3, U % 4, U % 5]
