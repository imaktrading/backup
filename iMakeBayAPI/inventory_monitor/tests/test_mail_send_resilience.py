"""公式 run_daily のメール送信 resilience regression (2026-06-19).

bug: 公式メール送信は retry/fallback 無し + 結果が print (Task Scheduler の pythonw で破棄)
→ DNS/SMTP blip で送信失敗すると メールも ログも 代替通知も無い完全 silent (= cycle 結果見落とし)。
修正: transient retry + mail_send.log 永続記録 + 失敗時 desktop ALERT (絶対 silent 化しない)。
"""
from __future__ import annotations

import sys
import time
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import run_daily as R  # noqa: E402


@pytest.fixture
def tmp_env(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "LOG_DIR", tmp_path)
    monkeypatch.setattr(R.Path, "home", staticmethod(lambda: tmp_path))
    (tmp_path / "OneDrive" / "デスクトップ").mkdir(parents=True)
    return tmp_path


def _desktop_alerts(tmp_path):
    return list((tmp_path / "OneDrive" / "デスクトップ").glob("ALERT_*mail_failed_*.txt"))


def test_record_failure_writes_log_and_desktop_alert(tmp_env):
    R._record_mail_result(False, "[公式] test", "ConnectionError: getaddrinfo failed")
    log = (tmp_env / "mail_send.log").read_text(encoding="utf-8")
    assert "NG" in log and "test" in log
    assert len(_desktop_alerts(tmp_env)) == 1  # 失敗は絶対 silent 化しない


def test_record_success_logs_ok_no_alert(tmp_env):
    R._record_mail_result(True, "[公式] ok-run")
    log = (tmp_env / "mail_send.log").read_text(encoding="utf-8")
    assert "OK" in log and "ok-run" in log
    assert _desktop_alerts(tmp_env) == []


def _inject_mail_modules(monkeypatch, send_fn, cfg=("a@x", "pw", "b@x")):
    fake_en = types.ModuleType("email_notifier")
    fake_en._send_via_gmail = send_fn
    monkeypatch.setitem(sys.modules, "email_notifier", fake_en)
    fake_auth = types.ModuleType("auth")
    fake_eg = types.ModuleType("auth.encrypted_gmail")
    fake_eg.load_gmail_config = lambda: cfg
    fake_auth.encrypted_gmail = fake_eg
    monkeypatch.setitem(sys.modules, "auth", fake_auth)
    monkeypatch.setitem(sys.modules, "auth.encrypted_gmail", fake_eg)
    monkeypatch.setattr(time, "sleep", lambda *a, **k: None)


def test_send_retries_transient_then_success(tmp_env, monkeypatch):
    calls = {"n": 0}

    def fake_send(addr, pw, to, subj, body):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise ConnectionError("Failed to resolve 'smtp.gmail.com' (getaddrinfo failed)")

    _inject_mail_modules(monkeypatch, fake_send)
    assert R._send_report_email("subj", "body") is True
    assert calls["n"] == 3
    assert "OK" in (tmp_env / "mail_send.log").read_text(encoding="utf-8")
    assert _desktop_alerts(tmp_env) == []


def test_send_persistent_failure_alerts_not_silent(tmp_env, monkeypatch):
    def fake_send(addr, pw, to, subj, body):
        raise ConnectionError("getaddrinfo failed")

    _inject_mail_modules(monkeypatch, fake_send)
    assert R._send_report_email("subj", "body") is False
    # 完全 silent でなく desktop ALERT + NG ログが残る
    assert len(_desktop_alerts(tmp_env)) == 1
    assert "NG" in (tmp_env / "mail_send.log").read_text(encoding="utf-8")


def test_send_skip_when_no_config_is_not_alerted(tmp_env, monkeypatch):
    """opt-in 未設定 (config None) は silent 化 risk でないので ALERT 出さない。"""
    _inject_mail_modules(monkeypatch, lambda *a: None, cfg=None)
    assert R._send_report_email("subj", "body") is False
    assert _desktop_alerts(tmp_env) == []
