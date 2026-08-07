"""復活 3点セット gate の regression test (2026-08-07 revive_qty1_impl §3).

依頼書 完了条件 3 「3点セットの回帰テスト」 の直接テスト。

`is_actively_in_stock` が (D=空 AND AK(巡回ERR)=空 AND O(チェック時刻)=直近cycle内)
を満たすかを判定し、 不成立 = 復活しない (fail-closed) を担保する。
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ebay_actions.revive_csv_generator import is_actively_in_stock  # noqa: E402


_DT_FMT = "%Y/%m/%d %H:%M:%S"


def _row(current_sold="", err_flag_prev="", checked_at=""):
    return {
        "current_sold": current_sold,
        "err_flag_prev": err_flag_prev,
        "checked_at": checked_at,
    }


def test_all_three_conditions_ok_returns_true():
    now = datetime(2026, 8, 7, 12, 0, 0)
    cycle_start = datetime(2026, 8, 7, 11, 55, 0)
    row = _row(current_sold="", err_flag_prev="", checked_at=now.strftime(_DT_FMT))
    ok, reason = is_actively_in_stock(row, cycle_start)
    assert ok is True
    assert reason == "ok"


def test_d_marked_sold_returns_false():
    """D=○ (or 〇) が残っている行は復活しない (前状態残存 or 未売切化)。"""
    cycle_start = datetime(2026, 8, 7, 11, 55, 0)
    for mark in ("○", "〇"):
        row = _row(current_sold=mark, err_flag_prev="",
                   checked_at="2026/08/07 12:00:00")
        ok, reason = is_actively_in_stock(row, cycle_start)
        assert ok is False
        assert reason == "d_marked_sold"


def test_ak_err_marker_returns_false():
    """AK 巡回ERR がある行 = 判定不能 → 復活しない (fail-closed)。"""
    cycle_start = datetime(2026, 8, 7, 11, 55, 0)
    row = _row(current_sold="", err_flag_prev="ERR3(2026-08-07)",
               checked_at="2026/08/07 12:00:00")
    ok, reason = is_actively_in_stock(row, cycle_start)
    assert ok is False
    assert reason == "ak_has_err_marker"


def test_empty_checked_at_returns_false():
    """O 列空欄 = 判定不能 → 復活しない。"""
    cycle_start = datetime(2026, 8, 7, 11, 55, 0)
    row = _row(current_sold="", err_flag_prev="", checked_at="")
    ok, reason = is_actively_in_stock(row, cycle_start)
    assert ok is False
    assert reason == "o_empty"


def test_unparseable_checked_at_returns_false():
    """O 列 parse 不能 → 復活しない (壊れた形式の残存 marker を通さない)。"""
    cycle_start = datetime(2026, 8, 7, 11, 55, 0)
    row = _row(current_sold="", err_flag_prev="", checked_at="invalid date")
    ok, reason = is_actively_in_stock(row, cycle_start)
    assert ok is False
    assert reason == "o_unparseable"


def test_checked_at_older_than_cycle_returns_false():
    """O が cycle_started_at より古い = 別 cycle 残存 → 復活しない。

    依頼書 実測: 143件すべてが直近 cycle で能動判定されていたが、 このテストは
    「前 cycle 残存」 の未来 fail-open を防ぐ regression として重要。
    """
    cycle_start = datetime(2026, 8, 7, 11, 55, 0)
    # cycle_start より 1 時間前 = 前 cycle
    old_ts = (cycle_start - timedelta(hours=1)).strftime(_DT_FMT)
    row = _row(current_sold="", err_flag_prev="", checked_at=old_ts)
    ok, reason = is_actively_in_stock(row, cycle_start)
    assert ok is False
    assert reason == "o_older_than_current_cycle"


def test_checked_at_exactly_at_cycle_start_returns_true():
    """境界: cycle_started_at ちょうどは 「以降」 に含める。"""
    cycle_start = datetime(2026, 8, 7, 11, 55, 0)
    row = _row(current_sold="", err_flag_prev="",
               checked_at=cycle_start.strftime(_DT_FMT))
    ok, reason = is_actively_in_stock(row, cycle_start)
    assert ok is True


def test_apply_gates_three_point_excludes_stale_rows():
    """apply_gates() で 3点セット違反行が deferred に落ちる (前状態残存の誤復活防止)。"""
    from ebay_actions.revive_csv_generator import apply_gates  # noqa: PLC0415

    cycle_start = datetime(2026, 8, 7, 11, 55, 0)
    now_ts = "2026/08/07 12:00:00"
    old_ts = "2026/08/07 09:00:00"
    candidates = [
        # ① D=空 AK=空 O=新 → gate 通過 (URL 白リストも AmazonでOK)
        {"row_index": 100, "url": "https://amazon.co.jp/dp/B1",
         "item_id": "IID_OK", "title": "OK", "current_sold": "",
         "err_flag_prev": "", "checked_at": now_ts, "sheet_label": "HIGH",
         "key_number": "K1", "category": "G-SHOCK",
         "price": "3000", "current_m_jpy_str": "3000"},
        # ② D=○ → 3点セット違反
        {"row_index": 101, "url": "https://amazon.co.jp/dp/B2",
         "item_id": "IID_DSOLD", "title": "D=○ 残", "current_sold": "○",
         "err_flag_prev": "", "checked_at": now_ts, "sheet_label": "HIGH",
         "key_number": "K2", "category": "G-SHOCK",
         "price": "3000", "current_m_jpy_str": "3000"},
        # ③ AK に marker → 3点セット違反
        {"row_index": 102, "url": "https://amazon.co.jp/dp/B3",
         "item_id": "IID_AKERR", "title": "AK err", "current_sold": "",
         "err_flag_prev": "ERR3(2026-08-07)", "checked_at": now_ts,
         "sheet_label": "HIGH", "key_number": "K3", "category": "G-SHOCK",
         "price": "3000", "current_m_jpy_str": "3000"},
        # ④ O が古い → 3点セット違反
        {"row_index": 103, "url": "https://amazon.co.jp/dp/B4",
         "item_id": "IID_OOLD", "title": "O 古", "current_sold": "",
         "err_flag_prev": "", "checked_at": old_ts, "sheet_label": "HIGH",
         "key_number": "K4", "category": "G-SHOCK",
         "price": "3000", "current_m_jpy_str": "3000"},
    ]

    # 採算 gate は「必ず OK になる」ように mock: rec_price=1.0 で全件通過
    allowed, deferred, price_hold = apply_gates(
        candidates=candidates,
        sheet_key_maps={"HIGH": {}},
        cycle_started_at=cycle_start,
        active_qty_map={},
        fetch_price_fn=lambda iid: (999.0, 0),
        compute_fn=lambda cost, med, cat: {"price": 1.0},
    )
    allowed_iids = {c["item_id"] for c in allowed}
    assert allowed_iids == {"IID_OK"}, f"expected only IID_OK, got {allowed_iids}"
    deferred_reasons = {c["item_id"]: c["skip_reason"] for c in deferred}
    assert deferred_reasons["IID_DSOLD"] == "d_marked_sold"
    assert deferred_reasons["IID_AKERR"] == "ak_has_err_marker"
    assert deferred_reasons["IID_OOLD"] == "o_older_than_current_cycle"
