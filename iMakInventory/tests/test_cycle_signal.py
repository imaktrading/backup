"""リバイスへの合図 (2026-10-14 B-20261014-004): 完走して書込が成功した時だけ書く."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cycle_signal as S  # noqa: E402


def test_decide_only_when_write_succeeded():
    assert S.decide("HIGH", {"ok": True}) == (True, "")
    assert S.decide("HIGH", {"ok": False, "reason": "スプシ書込失敗 APIError"}) == (False, "スプシ書込失敗 APIError")
    assert S.decide("HIGH", None)[0] is False
    assert S.decide("CAND", {"ok": True})[0] is False


def test_cand_is_not_a_signal_label():
    assert S.LABEL_OF_CYCLE.get("CAND") is None
    assert S.LABEL_OF_CYCLE["SHEET"] == "HIGH" and S.LABEL_OF_CYCLE["LOW"] == "LOW"


def test_signal_writes_row_and_logs(monkeypatch):
    got, logs = [], []
    monkeypatch.setattr(S, "write", lambda kind, row: got.append((kind, row)))
    r = S.signal("HIGH", "2026-10-14 13:30:14", {"ok": True, "written": 880, "m_changed": 12, "d_changed": 3},
                 1035, log=logs.append)
    assert r["written"] is True
    kind, row = got[0]
    assert kind == "HIGH" and row[0] == "HIGH" and row[3:7] == [1035, 880, 12, 3]
    assert "🔔 合図: 書いた [HIGH]" in logs[0]


def test_signal_not_written_still_logs(monkeypatch):
    logs = []
    monkeypatch.setattr(S, "write", lambda *_a: (_ for _ in ()).throw(AssertionError("書いてはいけない")))
    r = S.signal("LOW", "x", {"ok": False, "reason": "dry-run"}, 0, log=logs.append)
    assert r["written"] is False and "書かない [LOW]" in logs[0] and "dry-run" in logs[0]


def test_write_failure_does_not_raise(monkeypatch):
    logs = []
    def boom(*_a):
        raise RuntimeError("quota")
    monkeypatch.setattr(S, "write", boom)
    r = S.signal("HIGH", "x", {"ok": True}, 1, log=logs.append)
    assert r["written"] is False and "書けなかった" in logs[0]
