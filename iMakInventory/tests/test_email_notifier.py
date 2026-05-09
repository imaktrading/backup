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


def test_subject_success_uses_japanese_summary():
    from email_notifier import _format_subject
    s = _format_subject(_success_log())
    assert s.startswith("[OK]")
    assert "巡回" in s
    assert "受理 4 件" in s   # "Warning 4" の和訳


def test_subject_failure_uses_japanese_error():
    from email_notifier import _format_subject
    s = _format_subject(_failure_log("not_logged_in"))
    assert s.startswith("[NG]")
    assert "ログイン切れ" in s   # "not_logged_in" の和訳


def test_subject_skip_uses_japanese():
    from email_notifier import _format_subject
    s = _format_subject(_skip_log())
    assert s.startswith("[SKIP]")
    assert "取下げ対象なし" in s


def test_body_uses_japanese_section_headers():
    from email_notifier import _format_body
    body = _format_body(_success_log())
    assert "在庫監視" in body
    assert "eBay 取下げ" in body
    assert "ヘルス" in body
    assert "新規売切検知" in body
    assert "受理 4 件" in body


def test_body_failure_translates_error():
    from email_notifier import _format_body
    body = _format_body(_failure_log("SessionNotCreatedException: foo"))
    assert "失敗" in body
    assert "Chrome" in body  # SessionNotCreated → Chrome バージョン不一致


def test_translate_error_known_patterns():
    from email_notifier import _translate_error
    assert "ログイン切れ" in _translate_error("not_logged_in")
    assert "Chrome" in _translate_error("SessionNotCreatedException: ...")
    assert "input" in _translate_error("RuntimeError: input(): lost sys.stdin")
    assert "判定不安定" in _translate_error("upload result not detected (popup + history both inconclusive)")


def test_body_high_error_rate_shows_warning():
    """error_rate >= 50% は「異常高率」警告を出す (1/30 事故型対策)."""
    from email_notifier import _format_body
    log = _success_log()
    log["phases"]["monitor"]["errors"] = 441
    log["phases"]["monitor"]["processed"] = 514
    body = _format_body(log)
    assert "異常高率" in body
    assert "85%" in body or "86%" in body


def test_body_low_error_rate_says_temporary():
    """error_rate < 10% は「一時的」と表示."""
    from email_notifier import _format_body
    log = _success_log()
    log["phases"]["monitor"]["errors"] = 12
    log["phases"]["monitor"]["processed"] = 503
    body = _format_body(log)
    assert "一時的" in body


def test_body_revise_skipped_shows_no_target():
    """revise_csv が skipped の場合は「対象なし」表示 (CSV 生成 ? を出さない)."""
    from email_notifier import _format_body
    log = _success_log()
    log["status"] = "success_no_changes"
    log["phases"]["revise_csv"] = {"skipped": "no newly_sold"}
    log["phases"]["upload"] = {"skipped": "no csv"}
    body = _format_body(log)
    assert "取下げ対象   : なし" in body
    assert "CSV 生成" not in body
    assert "?" not in body  # `?` 出ない


def test_summarize_result_text():
    from email_notifier import _summarize_result_text
    assert _summarize_result_text("Warning 4 + safe Failure 0 + action-needed Failure 0") == "受理 4 件"
    assert "受理 1 件" in _summarize_result_text("Warning 1 + safe Failure 2 + action-needed Failure 0")
    assert "画像要件等 2 件" in _summarize_result_text("Warning 1 + safe Failure 2 + action-needed Failure 0")
    assert "要対応失敗 3 件" in _summarize_result_text("Warning 0 + safe Failure 0 + action-needed Failure 3")


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
    assert "eBay 取下げ" in sent_args["body"]


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
