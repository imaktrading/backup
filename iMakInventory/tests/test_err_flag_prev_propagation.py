"""_build_row_result が err_flag_prev を結果 dict まで伝播することの regression test.

2026-06-16 真因 fix: _build_row_result が err_flag_prev を含めていなかったため、
書込ループの `clear_err = bool(r.get("err_flag_prev"))` が常に False となり
  (1) 成功 scrape しても AK 列 (巡回ERR) が永久にクリアされない (古い marker 無限残留)
  (2) error 再mark 時も build_err_marker が prev="" 扱いで count が常に ×1
      (= PERSISTENT_THRESHOLD「要手動chk」が永久に発火しない)
の二重バグが発生していた。err_flag_prev が result まで運ばれることを固定する。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import monitor_listings as ML  # noqa: E402

pytestmark = pytest.mark.offline


def _sub(url, is_sold, error=None, raw="in_stock", price=1000):
    return {"url": url, "supplier": "mercari", "is_sold": is_sold,
            "raw_status": raw, "error": error, "price_jpy": price}


def _row(err_flag_prev, current_sold=""):
    return {"row_index": 3, "url": "https://jp.mercari.com/item/m1", "item_id": "111",
            "title": "t", "current_sold": current_sold, "current_n_jpy_str": "1000",
            "err_flag_prev": err_flag_prev}


def test_err_flag_prev_propagated_on_success():
    row = _row("⚠ scraper ×1 06/15 22:03")
    res = ML._build_row_result(row, [_sub(row["url"], is_sold=False)], hit_index=0)
    assert res.get("err_flag_prev") == "⚠ scraper ×1 06/15 22:03"


def test_err_flag_prev_propagated_on_error():
    row = _row("⚠ ReadTimeout ×1 06/15 22:03")
    res = ML._build_row_result(
        row, [_sub(row["url"], is_sold=None, error="ReadTimeoutError: x", raw="", price=None)],
        hit_index=-1)
    assert res.get("err_flag_prev") == "⚠ ReadTimeout ×1 06/15 22:03"


def test_clear_err_fires_for_previously_marked_success_row():
    # 書込ループの実際の判定式を再現: 前 cycle marker があり今回成功 → clear する
    row = _row("⚠ scraper ×1 06/15 22:03")
    res = ML._build_row_result(row, [_sub(row["url"], is_sold=False)], hit_index=0)
    clear_err = bool((res.get("err_flag_prev") or "").strip())
    assert clear_err is True  # 旧バグでは常に False だった


def test_no_clear_when_prev_blank():
    row = _row("")  # 前 cycle marker 無し → clear 書込しない (無駄書込回避)
    res = ML._build_row_result(row, [_sub(row["url"], is_sold=False)], hit_index=0)
    assert bool((res.get("err_flag_prev") or "").strip()) is False


def test_error_count_increments_with_propagated_prev():
    # err_flag_prev が伝播すれば build_err_marker の count が累積する (×1→×2)
    from datetime import datetime
    from err_flag import build_err_marker, marker_count
    now = datetime(2026, 6, 16, 1, 31)
    row = _row("⚠ ReadTimeout ×1 06/15 22:03")
    res = ML._build_row_result(
        row, [_sub(row["url"], is_sold=None, error="ReadTimeoutError: x", raw="", price=None)],
        hit_index=-1)
    marker = build_err_marker(res["error"], res.get("err_flag_prev", ""), now=now)
    assert marker_count(marker) == 2  # 旧バグでは常に 1
