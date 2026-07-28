"""eBay Trading API 日次呼出量の計測 + 上限接近の非-silent 告知 (2026-07-28).

2026-07-04 に 518 (Call usage limit reached) で取下げ upload が全滅し、取下げ漏れ 24 件が
蓄積した。当時は「当たってから」しか分からなかったので、消費量を計測して手前で知らせる。
計測は絶対に API 呼出を止めない (fail-safe)。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

pytestmark = pytest.mark.offline


@pytest.fixture()
def api(tmp_path, monkeypatch):
    import ebay_actions.trading_api_client as c
    monkeypatch.setattr(c, "API_USAGE_PATH", tmp_path / "usage.json")
    return c


# ---------------------------------------------------------------- 計測
def test_counts_per_call_and_total(api):
    api.record_api_call("ReviseInventoryStatus", today="2026-07-28")
    api.record_api_call("ReviseInventoryStatus", today="2026-07-28")
    d = api.record_api_call("GetItem", today="2026-07-28")
    assert d["total"] == 3
    assert d["by_call"] == {"ReviseInventoryStatus": 2, "GetItem": 1}


def test_resets_on_new_day(api):
    api.record_api_call("GetItem", today="2026-07-27")
    d = api.record_api_call("GetItem", today="2026-07-28")
    assert d["total"] == 1 and d["date"] == "2026-07-28"


def test_read_usage_ignores_other_day(api):
    api.record_api_call("GetItem", today="2026-07-27")
    assert api.read_api_usage(today="2026-07-28")["total"] == 0


def test_corrupted_file_does_not_raise(api):
    api.API_USAGE_PATH.write_text("{ broken", encoding="utf-8")
    d = api.record_api_call("GetItem", today="2026-07-28")
    assert d["total"] == 1                       # 数え直すだけ、例外は出さない
    assert api.read_api_usage(today="2026-07-28")["total"] == 1


def test_unwritable_path_does_not_raise(api, monkeypatch):
    """計測が書けなくても API 呼出は止めない"""
    monkeypatch.setattr(api, "API_USAGE_PATH", Path("Z:/nonexistent/dir/usage.json"))
    assert api.record_api_call("GetItem", today="2026-07-28")["total"] == 1
    assert api.read_api_usage(today="2026-07-28")["total"] == 0


def test_call_trading_records_each_attempt(api, monkeypatch):
    """実際の送信ごとに計上される (network retry も 1 回として数える)"""
    import requests

    calls = {"n": 0}

    def boom(*a, **k):
        calls["n"] += 1
        raise requests.exceptions.ConnectionError("dns")

    monkeypatch.setattr(requests, "post", boom)
    monkeypatch.setattr(api, "load_access_token", lambda: "tok")
    monkeypatch.setattr(api.time, "sleep", lambda _s: None)
    res = api._call_trading("ReviseInventoryStatus", "<xml/>", max_net_retries=2)
    assert res["success"] is False
    assert api.read_api_usage()["by_call"]["ReviseInventoryStatus"] == calls["n"] == 3


# ---------------------------------------------------------------- 告知
@pytest.fixture()
def rc_env(tmp_path, monkeypatch, api):
    import run_cycle as rc
    monkeypatch.setattr(rc, "EBAY_API_ALERT_STATE", tmp_path / "alert.json")
    emitted = []
    monkeypatch.setattr(rc, "_emit_nonsilent_alert",
                        lambda tag, subject, msg, test_mode=False: emitted.append((tag, subject, msg)))
    return rc, api, emitted


def test_no_alert_below_threshold(rc_env):
    rc, api, emitted = rc_env
    api.record_api_call("GetItem", n=int(rc.EBAY_API_DAILY_LIMIT * rc.EBAY_API_WARN_RATIO) - 1)
    u = rc._check_ebay_api_usage(test_mode=True)
    assert emitted == [] and u["total"] > 0


def test_alert_at_threshold_once_per_day(rc_env):
    rc, api, emitted = rc_env
    api.record_api_call("ReviseInventoryStatus",
                        n=int(rc.EBAY_API_DAILY_LIMIT * rc.EBAY_API_WARN_RATIO))
    first = rc._check_ebay_api_usage(test_mode=True)
    second = rc._check_ebay_api_usage(test_mode=True)
    assert first.get("alerted") is True
    assert second.get("alerted") is False        # 同日 2 回目は出さない
    assert len(emitted) == 1
    assert "上限" in emitted[0][1] and "ReviseInventoryStatus" in emitted[0][2]


def test_usage_unreadable_is_silent(rc_env, monkeypatch):
    """計測が壊れている時に誤報しない (実害検知は既存の 518 分類が担う)"""
    rc, api, emitted = rc_env
    monkeypatch.setattr(api, "read_api_usage", lambda *a, **k: (_ for _ in ()).throw(OSError("x")))
    assert rc._check_ebay_api_usage(test_mode=True) == {}
    assert emitted == []
