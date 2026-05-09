"""email_notifier - cycle 完了時に Gmail SMTP で結果メールを送信.

設計:
- **opt-in**: auth.encrypted_gmail に config が無ければ送信 skip (= 既存挙動完全保持)
- **fail-safe**: 送信失敗は cycle 全体を落とさない (raise しない、stderr に warning のみ)
- **冪等**: cycle_log を入力に取り、副作用なし (= retry / dry-run 容易)
- 件名で結果が一目で分かる: [OK] / [NG] / [SKIP]
- 本文は cycle_log 全 phase の human-readable 整形

使い方 (run_cycle から):
    from email_notifier import send_cycle_report
    send_cycle_report(cycle_log)   # 失敗しても cycle は止まらない
"""
from __future__ import annotations

import smtplib
import sys
from email.mime.text import MIMEText
from email.utils import formatdate
from typing import Any, Dict, Optional


def _format_subject(cycle_log: Dict[str, Any]) -> str:
    """[OK]/[NG]/[SKIP] の prefix + 結果サマリ 1 行."""
    status = cycle_log.get("status", "unknown")
    ts_start = cycle_log.get("ts_start", "")[:16].replace("T", " ")
    upload = cycle_log["phases"].get("upload", {}) if "phases" in cycle_log else {}

    if status == "success":
        prefix = "[OK]"
        result_text = upload.get("result_text", "")
        tail = f" {result_text}" if result_text else ""
    elif status in ("success_no_upload", "success_no_changes"):
        prefix = "[SKIP]"
        tail = ""
    elif status == "upload_failed":
        prefix = "[NG]"
        err = upload.get("error", "")
        # error の 1 行目だけ取り、長すぎる場合は切り詰め
        err_head = err.split("\n", 1)[0][:80] if err else "unknown"
        tail = f" {err_head}"
    elif status == "error":
        prefix = "[NG]"
        tail = f" cycle 例外: {cycle_log.get('error', '')[:80]}"
    else:
        prefix = "[?]"
        tail = ""

    return f"{prefix} iMakInventory cycle {ts_start}{tail}"


def _format_body(cycle_log: Dict[str, Any]) -> str:
    """cycle_log を human-readable に整形。全 phase の内訳."""
    lines = []
    lines.append("=" * 60)
    lines.append(f"status   : {cycle_log.get('status', 'unknown')}")
    lines.append(f"ts_start : {cycle_log.get('ts_start', '')}")
    lines.append(f"ts_end   : {cycle_log.get('ts_end', '')}")
    lines.append(f"sheet    : {cycle_log.get('sheet', '?')}")
    lines.append(f"test_mode: {cycle_log.get('test_mode', False)}")
    lines.append("")

    phases = cycle_log.get("phases", {}) or {}

    # pytest_precheck
    pp = phases.get("pytest_precheck", {})
    if pp:
        lines.append(f"[pytest_precheck] status={pp.get('status', '?')} elapsed={pp.get('elapsed_sec', '?')}s")

    # listing_verify
    lv = phases.get("listing_verify", {})
    if lv:
        if lv.get("error"):
            lines.append(f"[listing_verify] ERROR: {lv['error'].split(chr(10), 1)[0][:120]}")
        else:
            lines.append(f"[listing_verify] verified={lv.get('verified', '?')}")

    # backup
    bk = phases.get("backup", {}) or {}
    for sheet_label, info in bk.items():
        if isinstance(info, dict):
            b = info.get("backup", {}) or {}
            lines.append(f"[backup/{sheet_label}] tab={b.get('backup_tab_name', '?')} rows={b.get('row_count', '?')}")

    # monitor
    mon = phases.get("monitor", {}) or {}
    if mon:
        lines.append(
            f"[monitor] processed={mon.get('processed', '?')} "
            f"newly_sold={mon.get('newly_sold', '?')} "
            f"newly_in_stock={mon.get('newly_in_stock', '?')} "
            f"errors={mon.get('errors', '?')}"
        )
        by_sheet = mon.get("by_sheet", {}) or {}
        for label, s in by_sheet.items():
            if isinstance(s, dict):
                lines.append(
                    f"  {label}: processed={s.get('processed', '?')} "
                    f"newly_sold={s.get('newly_sold', '?')} "
                    f"newly_in_stock={s.get('newly_in_stock', '?')} "
                    f"errors={s.get('errors', '?')}"
                )

    # d_diff
    dd = phases.get("d_diff", {}) or {}
    for label, d in dd.items():
        if isinstance(d, dict):
            lines.append(
                f"[d_diff/{label}] newly_sold={d.get('newly_sold', '?')} "
                f"newly_in_stock={d.get('newly_in_stock', '?')} "
                f"unchanged={d.get('unchanged_count', '?')}"
            )

    # revise_csv
    rc = phases.get("revise_csv", {}) or {}
    if rc:
        lines.append(
            f"[revise_csv] candidates={rc.get('candidates', '?')} "
            f"allowed={rc.get('allowed', '?')} "
            f"deferred={rc.get('deferred', '?')} "
            f"reason={rc.get('reason', '?')}"
        )

    # upload
    up = phases.get("upload", {}) or {}
    if up:
        if "skipped" in up:
            lines.append(f"[upload] SKIPPED ({up['skipped']})")
        else:
            success = up.get("success")
            mark = "OK" if success else "NG"
            lines.append(f"[upload] {mark} csv_lines={up.get('csv_lines', '?')}")
            rt = up.get("result_text") or ""
            if rt:
                lines.append(f"  result : {rt}")
            if up.get("popup_text"):
                lines.append(f"  popup  : {up['popup_text'][:200]}")
            if up.get("error"):
                err_first = up["error"].split("\n", 1)[0]
                lines.append(f"  error  : {err_first[:200]}")
            if up.get("page_url"):
                lines.append(f"  page   : {up['page_url']}")

    # upload_health
    uh = phases.get("upload_health", {}) or {}
    if uh:
        lines.append(
            f"[upload_health] alert={uh.get('alert_fired')} "
            f"reason={uh.get('reason', '')} "
            f"streaks: not_logged_in={uh.get('not_logged_in_streak', 0)} "
            f"flaky={uh.get('flaky_streak', 0)} "
            f"generic={uh.get('generic_failure_streak', 0)}"
        )

    # audit_sample
    aud = phases.get("audit_sample", {}) or {}
    for label, a in aud.items():
        if isinstance(a, dict):
            lines.append(
                f"[audit_sample/{label}] sampled={a.get('sampled', '?')} "
                f"appended={a.get('appended', '?')}"
            )

    # cycle 例外
    if cycle_log.get("error"):
        lines.append("")
        lines.append(f"!!! CYCLE 例外: {cycle_log['error']}")
        tb = cycle_log.get("traceback", "")
        if tb:
            lines.append(tb[:1500])

    lines.append("")
    lines.append("=" * 60)
    lines.append("(automated by iMakInventory.email_notifier)")
    return "\n".join(lines)


def _send_via_gmail(address: str, app_password: str, to: str,
                    subject: str, body: str,
                    smtp_host: str = "smtp.gmail.com",
                    smtp_port: int = 465,
                    timeout: int = 30) -> None:
    """Gmail SMTP で送信。失敗時は例外 raise (呼出側で握る)."""
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = address
    msg["To"] = to
    msg["Date"] = formatdate(localtime=True)

    with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=timeout) as smtp:
        smtp.login(address, app_password)
        smtp.send_message(msg)


def send_cycle_report(cycle_log: Dict[str, Any]) -> Dict[str, Any]:
    """cycle 完了レポートを Gmail SMTP で送信。

    opt-in: encrypted_gmail.dat 不在なら skip。
    fail-safe: 送信失敗しても raise しない (cycle 全体を止めない)。

    Returns:
        {"sent": bool, "skipped_reason": Optional[str], "error": Optional[str]}
    """
    # 遅延 import (auth/encrypted_gmail は pywin32 依存、テストで不要なら触らない)
    try:
        from auth.encrypted_gmail import load_gmail_config  # noqa: PLC0415
    except Exception as e:
        return {"sent": False, "skipped_reason": None,
                "error": f"import failed: {type(e).__name__}: {e}"}

    cfg = load_gmail_config()
    if cfg is None:
        return {"sent": False,
                "skipped_reason": "encrypted_gmail.dat 不在 (= opt-in 未有効化)",
                "error": None}

    address, app_password, to = cfg

    try:
        subject = _format_subject(cycle_log)
        body = _format_body(cycle_log)
        _send_via_gmail(address, app_password, to, subject, body)
        return {"sent": True, "skipped_reason": None, "error": None}
    except Exception as e:
        msg = f"send failed: {type(e).__name__}: {e}"
        # cycle を止めないため stderr に warning のみ
        print(f"  ⚠️ email_notifier: {msg}", file=sys.stderr)
        return {"sent": False, "skipped_reason": None, "error": msg}


# ----------------------------------------------------------------------------
# CLI: 動作確認用 (tools/setup_email.py で credentials 保存後の smoke test)
# ----------------------------------------------------------------------------
def main():
    """CLI: ダミー cycle_log を 1 通送信 (smoke test 用)."""
    dummy_log = {
        "ts_start": "2026-05-09T12:34:56",
        "ts_end": "2026-05-09T13:00:00",
        "sheet": "both",
        "test_mode": True,
        "status": "success",
        "phases": {
            "monitor": {"processed": 100, "newly_sold": 1, "newly_in_stock": 0, "errors": 0},
            "revise_csv": {"candidates": 1, "allowed": 1, "deferred": 0, "reason": "OK"},
            "upload": {"success": True, "csv_lines": 1,
                       "result_text": "Warning 1 + safe Failure 0 + action-needed Failure 0",
                       "error": None},
            "upload_health": {"alert_fired": False, "reason": "",
                              "not_logged_in_streak": 0, "flaky_streak": 0,
                              "generic_failure_streak": 0},
        },
    }
    res = send_cycle_report(dummy_log)
    print(res)


if __name__ == "__main__":
    main()
