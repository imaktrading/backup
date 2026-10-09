"""用の済んだ担当の窓を閉じる: 待機中で5分動いていない・台帳に持ち物が無い時だけ (2026-10-09 ユーザー)。"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import agent_board as A  # noqa: E402

NOW = dt.datetime(2026, 10, 9, 17, 0)


def test_idle_enough_only_after_quiet_minutes():
    assert A.idle_enough({"state": "idle", "since": "2026-10-09T16:50:00"}, NOW)
    assert not A.idle_enough({"state": "idle", "since": "2026-10-09T16:58:00"}, NOW)
    assert not A.idle_enough({"state": "busy", "since": "2026-10-09T16:00:00"}, NOW)
    assert not A.idle_enough({"state": "ask", "since": "2026-10-09T16:00:00"}, NOW)
    assert not A.idle_enough({"state": "idle", "since": ""}, NOW)      # いつから待機か判らなければ閉じない


def test_open_keys_in_ledger():
    cur = {"1": {"to": "重複くん", "state": "受け取った"},
           "2": {"to": "リバイス", "state": "閉じた"},
           "3": {"to": "カタログ", "state": "判断済"},
           "4": {"to": "抽出くん", "state": "返した"},
           "5": {"to": "ADV", "state": "受付"}}
    assert A.open_keys_in_ledger(cur) == {"DEDUPE", "CATALOG"}


def test_keep_open_never_closed():
    for k in ("HQ", "ADV", "ALPHA", "BRAVO", "RELAY"):
        ok, _ = A.close_window(k)
        assert not ok
