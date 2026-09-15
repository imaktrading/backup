"""補URL③ が Sheets の読み取り上限 (429) で即落ちしていた / 落ちた走行で「件数が減らない」と誤報 (2026-09-15).

18:03 補URL③ 補充: `_read_high` が 429 で returncode=1。パネルは失敗した走行でも件数を突き合わせ、
「押しても件数が減りませんでした (17件 → 17件)」と出した。
"""
import os
import sys
import types

_HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_HQ, "tools"))

import psa_hoju_fill as H  # noqa: E402


def _fake_gspread(monkeypatch, fail_times, err="APIError: [429]: Quota exceeded"):
    calls = {"n": 0}

    class WS:
        id = H.HIGH_GID

        def get_all_values(self):
            calls["n"] += 1
            if calls["n"] <= fail_times:
                raise Exception(err)
            return [["A"], ["x"]]

    class SH:
        def worksheets(self):
            return [WS()]

    class GC:
        def open_by_key(self, _k):
            return SH()

    import gspread
    from google.oauth2 import service_account
    monkeypatch.setattr(gspread, "authorize", lambda _c: GC())
    monkeypatch.setattr(service_account.Credentials, "from_service_account_file",
                        classmethod(lambda cls, *a, **k: object()))
    return calls


def test_quota_error_waits_and_reads_again(monkeypatch):
    calls = _fake_gspread(monkeypatch, fail_times=2)
    waits = []
    assert H._read_high(sleep=waits.append) == [["A"], ["x"]]
    assert waits == [20, 40] and calls["n"] == 3


def test_other_errors_are_not_swallowed(monkeypatch):
    _fake_gspread(monkeypatch, fail_times=5, err="PermissionError: 403")
    try:
        H._read_high(sleep=lambda s: None)
    except Exception as e:
        assert "403" in str(e)
    else:
        raise AssertionError("429 以外を握りつぶしている")


def test_gives_up_after_retries(monkeypatch):
    _fake_gspread(monkeypatch, fail_times=99)
    waits = []
    try:
        H._read_high(sleep=waits.append)
    except Exception as e:
        assert "429" in str(e)
    assert waits == [20, 40, 60]


def test_panel_does_not_check_badge_after_a_failed_run():
    src = open(os.path.join(_HQ, "control_panel.py"), encoding="utf-8").read()
    assert "self._check_badge_moved(failed=item[1] not in (0, None))" in src
    i = src.index("def _check_badge_moved(self, failed=False):")
    body = src[i:i + 900]
    assert "if failed" in body, "失敗した走行でも突き合わせている"
