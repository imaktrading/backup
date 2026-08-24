"""eBay 日次API上限 (518) を「ただの upload 失敗」と混ぜない — 2026-08-24.

事故: 08-24 11:00 に上限到達 → 取下げが 1 件も送れず、売切品 6 件が
「eBay で買える」まま最大 5 時間残った。デスクトップに出たのは
「upload 失敗 3 回連続 / total=4 ok=0 ng=4」だけで、原因も回復時刻も書いていなかった。

固定すること:
  1. 失敗理由の文字列に 518 が載る (載らないと通知が原因を名指しできない)
  2. 518 は専用の通知になり、本文に「時間で回復する」「取下げは保留されている」が入る
  3. ログイン切れ等 他の原因の通知を壊さない
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import upload_health as uh  # noqa: E402


def test_518_gets_its_own_alert():
    title, body = uh._critical_alert_message(
        "Trading API revise: total=5 ok=0 ng=5 / 全件 ebay_api_daily_limit_518",
        "csv.csv", 5, "2026-08-24T13:30:03", 3)

    assert "API 上限" in title
    assert "518" in body
    assert "16:00" in body            # いつ戻るかを書く
    assert "キューに残っていて" in body  # 取下げ義務が消えていないことを書く


def test_518_is_treated_as_critical():
    """2 回失敗するまで黙っていない (即座に出す)."""
    assert any(c in "Trading API revise: ... / 全件 ebay_api_daily_limit_518"
               for c in uh.CRITICAL_ERRORS)


def test_login_lost_alert_is_unchanged():
    title, body = uh._critical_alert_message(
        "not_logged_in", "csv.csv", 3, "2026-08-24T13:30:03", 1)

    assert "ログイン切れ" in title
    assert "518" not in body


def test_generic_failure_still_generic():
    title, _ = uh._critical_alert_message(
        "Trading API revise: total=5 ok=0 ng=5", "csv.csv", 5, "2026-08-24T13:30:03", 2)

    assert "API 上限" not in title


def test_cycle_error_string_names_the_limit():
    """run_cycle が作る失敗理由に 518 が載ること (通知の入力になる)."""
    import run_cycle  # noqa: PLC0415
    from unittest.mock import patch  # noqa: PLC0415

    result = {"success": False, "total": 5, "ok": 0, "ng": 5, "rate_limited_failure": 5}
    with patch.object(run_cycle, "upload_csv_via_trading_api", return_value=result):
        out = run_cycle._phase_upload("csv_output/x.csv", test_mode=True)

    assert "ebay_api_daily_limit_518" in out["error"]


def test_cycle_error_string_partial_limit():
    import run_cycle  # noqa: PLC0415
    from unittest.mock import patch  # noqa: PLC0415

    result = {"success": False, "total": 5, "ok": 2, "ng": 3, "rate_limited_failure": 1}
    with patch.object(run_cycle, "upload_csv_via_trading_api", return_value=result):
        out = run_cycle._phase_upload("csv_output/x.csv", test_mode=True)

    assert "内 ebay_api_daily_limit_518 1" in out["error"]


def test_cycle_error_string_without_limit():
    import run_cycle  # noqa: PLC0415
    from unittest.mock import patch  # noqa: PLC0415

    result = {"success": False, "total": 5, "ok": 0, "ng": 5, "rate_limited_failure": 0}
    with patch.object(run_cycle, "upload_csv_via_trading_api", return_value=result):
        out = run_cycle._phase_upload("csv_output/x.csv", test_mode=True)

    assert "518" not in out["error"]
