"""監査のスプシ読込を 1 回の瞬断で諦めない — 2026-08-30.

事故: 08-30 10:00 の reverse_audit が `sheet_read_failed: LOW APIError` で中断。
監査は「取下げ漏れゼロ」を毎日証明する唯一の客観証拠なので、落ちた日は
「乖離ゼロを証明できない日」になる。しかも記録に残ったのは例外の型名だけで、
429 (混雑) なのか 500 なのかも分からなかった (= 次に起きても原因を追えない)。

固定すること:
  1. 一時エラーは間隔を空けて取り直す (2 回目で成功したら監査は続行する)
  2. 全部失敗した時だけ中断する (部分結果で「ゼロ件」と誤読させない)
  3. 記録に **例外の中身** を残す (型名だけにしない)
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import reverse_audit as ra  # noqa: E402


def test_retries_and_succeeds_on_second_attempt():
    calls = {"n": 0}

    def flaky(_sid):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("APIError: [429] Quota exceeded")
        return "SH"

    with patch.object(ra, "open_sheet_by_id", side_effect=flaky), \
         patch.object(ra, "get_listings_worksheet", return_value="WS"), \
         patch.object(ra, "read_listings_rows", return_value=[{"row_index": 2}]), \
         patch.object(ra.time, "sleep"):
        sh, rows = ra._read_sheet_rows_with_retry("sid", "LOW", only_with_url=False)

    assert calls["n"] == 2          # 1 回目の失敗で諦めない
    assert sh == "SH"
    assert len(rows) == 1


def test_gives_up_after_all_attempts():
    """全部失敗したら例外を上げる (= 中断。部分結果を返さない)."""
    with patch.object(ra, "open_sheet_by_id", side_effect=RuntimeError("APIError: [500]")), \
         patch.object(ra.time, "sleep"):
        with pytest.raises(RuntimeError):
            ra._read_sheet_rows_with_retry("sid", "LOW", only_with_url=False, attempts=3)


def test_attempt_count_is_respected():
    calls = {"n": 0}

    def always_fail(_sid):
        calls["n"] += 1
        raise RuntimeError("APIError: [503]")

    with patch.object(ra, "open_sheet_by_id", side_effect=always_fail), \
         patch.object(ra.time, "sleep"):
        with pytest.raises(RuntimeError):
            ra._read_sheet_rows_with_retry("sid", "LOW", only_with_url=False, attempts=2)

    assert calls["n"] == 2


def test_error_record_keeps_the_message():
    """記録に例外の中身が残る (型名だけだと次に起きた時に原因を追えない)."""
    with patch.object(ra, "_fetch_ebay_qty_map", return_value={"1": 1}), \
         patch.object(ra, "_read_sheet_rows_with_retry",
                      side_effect=RuntimeError("APIError: [429] Quota exceeded for reads")), \
         patch.object(ra.time, "sleep"):
        res = ra.run_reverse_audit(high_sheet_id="h", low_sheet_id="l", write_log=False)

    assert res["mismatch_count"] == -1          # fail-closed で中断
    assert "429" in res["error"]                # 中身が残っている
    assert "Quota exceeded" in res["error"]
