"""cycle レポートメールの送信リトライ + 証跡 (2026-08-09).

事故: 08-09 14:45 の LOW cycle でメール送信が 1 回失敗しただけで通知が落ち、
desktop alert file (ALERT_iMakInventory_mail_failed_2026-08-09_14.txt) 送りになった。
cycle 自体は success / action_required=0 で実害なしだが、**通知経路が一発勝負**だったのが問題。
公式監視くん側は 2026-06-19 に retry 化済み ([[koshiki_mail_silent_fail_fixed]])。同じ方式に揃える。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

pytestmark = pytest.mark.offline

CYCLE = {"ts_start": "2026-08-09T14:45:03", "ts_end": "2026-08-09T16:34:55",
         "status": "success", "sheet": "low",
         "phases": {"monitor": {"processed": 836, "newly_sold": 10, "newly_in_stock": 8,
                                "errors": 1, "error_rows": [], "by_sheet": {}},
                    "action_required_summary": {"count": 0, "items": []}}}


@pytest.fixture()
def en(tmp_path, monkeypatch):
    import email_notifier as m
    monkeypatch.setattr(m, "MAIL_LOG_PATH", tmp_path / "mail_send.log")
    monkeypatch.setattr(m, "SEND_RETRY_WAITS", [0, 0])
    monkeypatch.setattr(m.time, "sleep", lambda _s: None)
    monkeypatch.setitem(sys.modules, "auth.encrypted_gmail", _FakeAuth())
    return m


class _FakeAuth:
    @staticmethod
    def load_gmail_config():
        return ("a@example.com", "pw", "to@example.com")


def _mail_log(en):
    p = en.MAIL_LOG_PATH
    return p.read_text(encoding="utf-8") if p.exists() else ""


def test_succeeds_first_attempt(en, monkeypatch):
    calls = []
    monkeypatch.setattr(en, "_send_via_gmail", lambda *a: calls.append(a))
    res = en.send_cycle_report(CYCLE)
    assert res["sent"] is True and res["attempts"] == 1 and len(calls) == 1
    assert "OK | attempts=1" in _mail_log(en)


def test_retries_and_succeeds(en, monkeypatch):
    """★本命: 1 回目が瞬断で落ちても 2 回目で通知が届く"""
    n = {"i": 0}

    def flaky(*a):
        n["i"] += 1
        if n["i"] == 1:
            raise OSError("[Errno 11001] getaddrinfo failed")

    monkeypatch.setattr(en, "_send_via_gmail", flaky)
    res = en.send_cycle_report(CYCLE)
    assert res["sent"] is True and res["attempts"] == 2
    assert "OK | attempts=2" in _mail_log(en)


def test_all_attempts_fail_reports_error(en, monkeypatch):
    """3 回とも落ちたら sent=False を返す (呼び出し側が desktop alert に倒す)"""
    def boom(*a):
        raise smtp_error()

    def smtp_error():
        import smtplib
        return smtplib.SMTPServerDisconnected("Connection unexpectedly closed")

    monkeypatch.setattr(en, "_send_via_gmail", boom)
    res = en.send_cycle_report(CYCLE)
    assert res["sent"] is False and res["attempts"] == 3
    assert "SMTPServerDisconnected" in res["error"]
    assert "NG | attempts=3" in _mail_log(en)


def test_opt_in_disabled_is_not_a_failure(en, monkeypatch):
    """credentials 未設定は「失敗」ではない (desktop alert を出さない)"""
    monkeypatch.setitem(sys.modules, "auth.encrypted_gmail",
                        type("M", (), {"load_gmail_config": staticmethod(lambda: None)}))
    res = en.send_cycle_report(CYCLE)
    assert res["sent"] is False and res["skipped_reason"] and res["error"] is None


def test_mail_log_failure_does_not_break_send(en, monkeypatch):
    monkeypatch.setattr(en, "MAIL_LOG_PATH", Path("Z:/nope/mail.log"))
    monkeypatch.setattr(en, "_send_via_gmail", lambda *a: None)
    assert en.send_cycle_report(CYCLE)["sent"] is True
