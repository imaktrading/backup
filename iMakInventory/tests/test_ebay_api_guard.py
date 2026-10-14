"""eBay Trading の歯止め (2026-10-15 手順書 RUNBOOK_EBAY_API_QUOTA §7)."""
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ebay_actions import trading_api_client as T  # noqa: E402


def _setup(monkeypatch, tmp_path, by_caller, total=0):
    monkeypatch.setattr(T, "API_USAGE_PATH", tmp_path / "u.json")
    monkeypatch.setattr(T, "API_NOTIFY_STATE", tmp_path / "n.json")
    (tmp_path / "u.json").write_text(json.dumps(
        {"date": T.ebay_day(), "total": total, "by_call": {}, "by_caller": by_caller}), encoding="utf-8")
    sent = []
    import monitor_listings
    monkeypatch.setattr(monitor_listings, "log", lambda line: sent.append(line))
    monkeypatch.setattr(T, "_caller", lambda: "ebay_supplier_sync.py")
    return sent


def test_ebay_day_is_us_pacific():
    assert T.ebay_day(datetime(2026, 10, 15, 15, 59)) == "2026-10-14"   # 夏: 16 時で替わる
    assert T.ebay_day(datetime(2026, 10, 15, 16, 0)) == "2026-10-15"
    assert T.ebay_day(datetime(2026, 11, 15, 16, 30)) == "2026-11-14"   # 冬: 17 時で替わる
    assert T.ebay_day(datetime(2026, 11, 15, 17, 0)) == "2026-11-15"


def test_caller_over_limit_is_stopped_but_takedown_passes(monkeypatch, tmp_path):
    sent = _setup(monkeypatch, tmp_path, {"GetItem@ebay_supplier_sync.py": 1000})
    assert T.guard("GetItem")
    assert T.guard("ReviseInventoryStatus") is None           # 取下げ・数量 0 は止めない
    assert T.guard("EndFixedPriceItem") is None
    assert len(sent) == 1                                     # 知らせるのは 1 日 1 回
    T.guard("GetItem")
    assert len(sent) == 1


def test_other_caller_not_stopped(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, {"GetItem@audit_buyable_vs_supplier.py": 1500})
    assert T.guard("GetItem") is None


def test_total_warn_once(monkeypatch, tmp_path):
    sent = _setup(monkeypatch, tmp_path, {}, total=3100)
    assert T.guard("GetItem") is None
    T.guard("GetItem")
    assert len(sent) == 1


def test_record_counts_by_caller(monkeypatch, tmp_path):
    monkeypatch.setattr(T, "API_USAGE_PATH", tmp_path / "u.json")
    monkeypatch.setattr(T, "_caller", lambda: "quick_watch.py")
    T.record_api_call("GetItem")
    T.record_api_call("GetItem")
    u = T.read_api_usage()
    assert u["total"] == 2 and u["by_caller"]["GetItem@quick_watch.py"] == 2


def test_call_trading_returns_failure_when_guarded(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, {"GetItem@ebay_supplier_sync.py": 1000})
    import requests
    monkeypatch.setattr(requests, "post", lambda *a, **k: (_ for _ in ()).throw(AssertionError("送ってはいけない")))
    r = T._call_trading("GetItem", "<x/>", access_token="t")
    assert r["success"] is False and r["error_code"] == "iMak_guard"


class _R:
    def __init__(self, text):
        self.status_code, self.text = 200, text


Q518 = "<Ack>Failure</Ack><Errors><ErrorCode>518</ErrorCode><LongMessage>exceeded usage limit</LongMessage></Errors>"
OK = "<Ack>Success</Ack>"


def _setup_sub(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, {})
    sent = []
    import requests
    def post(url, headers=None, data=None, timeout=None):
        sent.append(headers["X-EBAY-API-IAF-TOKEN"])
        return _R(Q518 if headers["X-EBAY-API-IAF-TOKEN"] == "MAIN" else OK)
    monkeypatch.setattr(requests, "post", post)
    monkeypatch.setattr(T, "_sub_access_token", lambda: "SUB")
    return sent


def test_takedown_retries_on_sub_key_only_after_518(monkeypatch, tmp_path):
    sent = _setup_sub(monkeypatch, tmp_path)
    r = T._call_trading("ReviseInventoryStatus", "<x/>", access_token="MAIN")
    assert sent == ["MAIN", "SUB"] and r["success"] is True
    assert T.read_api_usage()["by_call"]["ReviseInventoryStatus(2つ目の鍵)"] == 1


def test_non_takedown_never_uses_sub_key(monkeypatch, tmp_path):
    sent = _setup_sub(monkeypatch, tmp_path)
    r = T._call_trading("GetItem", "<x/>", access_token="MAIN")
    assert sent == ["MAIN"] and r["success"] is False
