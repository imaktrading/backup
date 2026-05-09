"""email_notifier の regression test (送信は mock、整形は実物)."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _success_log():
    return {
        "ts_start": "2026-05-09T17:30:02",
        "ts_end": "2026-05-09T18:05:04",
        "sheet": "both",
        "test_mode": False,
        "status": "success",
        "phases": {
            "monitor": {"processed": 503, "newly_sold": 4, "newly_in_stock": 0, "errors": 12,
                        "by_sheet": {"SHEET": {"processed": 503, "newly_sold": 4,
                                                "newly_in_stock": 0, "errors": 12}}},
            "d_diff": {"SHEET": {"newly_sold": 4, "newly_in_stock": 0, "unchanged_count": 499}},
            "revise_csv": {"candidates": 4, "allowed": 4, "deferred": 0, "reason": "OK"},
            "upload": {"success": True, "csv_lines": 4,
                       "result_text": "Warning 4 + safe Failure 0 + action-needed Failure 0",
                       "error": None},
            "upload_health": {"alert_fired": False, "reason": "",
                              "not_logged_in_streak": 0, "flaky_streak": 0,
                              "generic_failure_streak": 0},
        },
    }


def _failure_log(error="not_logged_in"):
    log = _success_log()
    log["status"] = "upload_failed"
    log["phases"]["upload"] = {"success": False, "csv_lines": 4,
                                "result_text": "", "error": error}
    log["phases"]["upload_health"] = {"alert_fired": True, "reason": "not_logged_in_immediate",
                                       "not_logged_in_streak": 1, "flaky_streak": 0,
                                       "generic_failure_streak": 0}
    return log


def _skip_log():
    log = _success_log()
    log["status"] = "success_no_upload"
    log["phases"]["upload"] = {"skipped": "csv_path none or skip_upload"}
    log["phases"].pop("upload_health", None)
    return log


def test_subject_success_includes_OK_and_result_text():
    from email_notifier import _format_subject
    s = _format_subject(_success_log())
    assert s.startswith("[OK]")
    assert "Warning 4" in s


def test_subject_failure_includes_NG_and_error_head():
    from email_notifier import _format_subject
    s = _format_subject(_failure_log("not_logged_in"))
    assert s.startswith("[NG]")
    assert "not_logged_in" in s


def test_subject_skip_includes_SKIP():
    from email_notifier import _format_subject
    s = _format_subject(_skip_log())
    assert s.startswith("[SKIP]")


def test_body_contains_all_phase_summaries():
    from email_notifier import _format_body
    body = _format_body(_success_log())
    assert "[monitor]" in body
    assert "[d_diff/SHEET]" in body
    assert "[revise_csv]" in body
    assert "[upload]" in body
    assert "Warning 4" in body
    assert "[upload_health]" in body


def test_body_failure_includes_error_line():
    from email_notifier import _format_body
    body = _format_body(_failure_log("SessionNotCreatedException: foo"))
    assert "NG" in body
    assert "SessionNotCreatedException" in body


def test_send_skips_when_no_config(monkeypatch, tmp_path):
    """encrypted_gmail.dat 不在時は送信せず skip 返却 (= opt-in)."""
    from auth import encrypted_gmail
    monkeypatch.setattr(encrypted_gmail, "ENCRYPTED_GMAIL_FILE", tmp_path / ".no_such_file.dat")
    from email_notifier import send_cycle_report
    res = send_cycle_report(_success_log())
    assert res["sent"] is False
    assert res["skipped_reason"] is not None
    assert res["error"] is None


def test_send_calls_smtp_when_config_present(monkeypatch, tmp_path):
    """config あれば _send_via_gmail が呼ばれる (実 SMTP は patch)."""
    from auth import encrypted_gmail
    monkeypatch.setattr(encrypted_gmail, "ENCRYPTED_GMAIL_FILE", tmp_path / ".encrypted_gmail.dat")
    encrypted_gmail.save_gmail_config("a@example.com", "abcdefghijklmnop", "b@example.com")

    sent_args = {}

    def fake_send(address, app_password, to, subject, body, **kw):
        sent_args.update(address=address, app_password=app_password, to=to,
                         subject=subject, body=body)

    with patch("email_notifier._send_via_gmail", side_effect=fake_send):
        from email_notifier import send_cycle_report
        res = send_cycle_report(_success_log())

    assert res["sent"] is True
    assert sent_args["address"] == "a@example.com"
    assert sent_args["to"] == "b@example.com"
    assert sent_args["subject"].startswith("[OK]")
    assert "[upload]" in sent_args["body"]


def test_send_swallows_smtp_error(monkeypatch, tmp_path):
    """SMTP 例外でも raise せず error フィールドで返す (= cycle 全体を止めない)."""
    from auth import encrypted_gmail
    monkeypatch.setattr(encrypted_gmail, "ENCRYPTED_GMAIL_FILE", tmp_path / ".encrypted_gmail.dat")
    encrypted_gmail.save_gmail_config("a@example.com", "abcdefghijklmnop", "b@example.com")

    def boom(*a, **kw):
        raise ConnectionError("simulated SMTP failure")

    with patch("email_notifier._send_via_gmail", side_effect=boom):
        from email_notifier import send_cycle_report
        res = send_cycle_report(_success_log())

    assert res["sent"] is False
    assert res["error"] is not None
    assert "ConnectionError" in res["error"]
