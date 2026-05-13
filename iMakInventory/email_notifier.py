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


def _summarize_result_text(result_text: str) -> str:
    """eBay 上の result_text を日本語サマリに変換.

    eBay FileExchange の result_text 例:
        "Warning 4 + safe Failure 0 + action-needed Failure 0"
    分類:
        - Warning N      : 受理されたが軽微指摘あり (= 取下げ成功扱い)
        - safe Failure N : eBay 側の都合 (画像要件等)、当方の処理は問題なし
        - action-needed Failure N : 要対応の失敗 (実害あり)
    """
    if not result_text:
        return ""
    import re
    w = re.search(r"Warning\s*(\d+)", result_text)
    sf = re.search(r"safe\s*Failure\s*(\d+)", result_text)
    af = re.search(r"action-needed\s*Failure\s*(\d+)", result_text)
    parts = []
    if w:
        parts.append(f"受理 {w.group(1)} 件")
    if sf and sf.group(1) != "0":
        parts.append(f"画像要件等 {sf.group(1)} 件")
    if af and af.group(1) != "0":
        parts.append(f"要対応失敗 {af.group(1)} 件")
    return " / ".join(parts) if parts else result_text


def _translate_error(err: str) -> str:
    """よくあるエラー文字列を日本語に簡訳."""
    if not err:
        return ""
    head = err.split("\n", 1)[0]
    low = head.lower()
    if "not_logged_in" in low or "not logged in" in low:
        return "eBay ログイン切れ"
    if "result_csv_download_failed" in low and "503" in low:
        return "結果 CSV 取得失敗 (eBay サーバ 503、Submit は届いている可能性大)"
    if "result_csv_download_failed" in low:
        return "結果 CSV 取得失敗 (Submit は届いている可能性大、要 eBay 履歴目視)"
    if "chrome not reachable" in low:
        return "Chrome 起動失敗 (profile lock 残存 等)"
    if "sessionnotcreated" in low or "this version of chromedriver" in low:
        return "Chrome バージョン不一致 (driver 更新待ち)"
    if "lost sys.stdin" in low:
        return "cron 環境で input() 失敗 (旧版 hotfix で対処済)"
    if "upload result not detected" in low:
        return "判定不安定 (eBay 側受理済みの可能性大、要 eBay 履歴目視)"
    if "action_needed_failure" in low:
        return "eBay 側で取下げ拒否 (画像要件 / Item Specifics 不備等、listing 個別対応必要)"
    if "timeout" in low:
        return "タイムアウト (一時的)"
    return head[:120]


def _is_submit_likely_succeeded(err: str) -> bool:
    """error 文字列から「Submit は実は届いている」が推定できるか判定.

    503 / 判定不安定 / 履歴に出てこない 等は「結果取得失敗だけで Submit は届いている」
    可能性が高い → 「異常」ではなく「警告」と表現する。
    """
    if not err:
        return False
    low = err.lower()
    return ("result_csv_download_failed" in low
            or "upload result not detected" in low
            or "result_not_in_history" in low)


def _format_subject(cycle_log: Dict[str, Any]) -> str:
    """件名: [OK]/[NG]/[SKIP] + 巡回時刻 + 結果 1 行サマリ."""
    status = cycle_log.get("status", "unknown")
    ts_start = cycle_log.get("ts_start", "")[:16].replace("T", " ")
    upload = cycle_log["phases"].get("upload", {}) if "phases" in cycle_log else {}

    if status == "success":
        prefix = "[OK]"
        summary = _summarize_result_text(upload.get("result_text", ""))
        tail = f" 取下げ {summary}" if summary else ""
    elif status in ("success_no_upload", "success_no_changes"):
        prefix = "[SKIP]"
        tail = " 取下げ対象なし"
    elif status == "upload_failed":
        err = upload.get('error', '')
        if _is_submit_likely_succeeded(err):
            prefix = "[警告]"
            tail = f" 結果取得不能 (Submit 届いた可能性大): {_translate_error(err)}"
        else:
            prefix = "[NG]"
            tail = f" 取下げ失敗: {_translate_error(err)}"
    elif status == "error":
        prefix = "[NG]"
        tail = f" 巡回中に例外: {_translate_error(cycle_log.get('error', ''))}"
    else:
        prefix = "[?]"
        tail = f" 不明な状態: {status}"

    return f"{prefix} iMakInventory 巡回 {ts_start}{tail}"


def _fmt_ts(iso_ts: str) -> str:
    """ISO 形式 (2026-05-09T17:30:02) → '2026-05-09 17:30' に短縮."""
    if not iso_ts:
        return "?"
    return iso_ts[:16].replace("T", " ")


def _fmt_duration(start_iso: str, end_iso: str) -> str:
    """所要時間を '35分' / '1時間2分' で返す."""
    try:
        from datetime import datetime  # noqa: PLC0415
        s = datetime.fromisoformat(start_iso)
        e = datetime.fromisoformat(end_iso)
        sec = int((e - s).total_seconds())
        if sec < 60:
            return f"{sec}秒"
        m, s = divmod(sec, 60)
        if m < 60:
            return f"{m}分{s:02d}秒" if s else f"{m}分"
        h, m = divmod(m, 60)
        return f"{h}時間{m:02d}分"
    except Exception:
        return "?"


_STATUS_JP = {
    "success": "正常 (取下げ実施)",
    "success_no_upload": "正常 (取下げ対象なし)",
    "success_no_changes": "正常 (在庫変動なし)",
    "upload_failed": "異常: 取下げ失敗",
    "error": "異常: 巡回中に例外",
}


def _status_label(cycle_log: Dict[str, Any]) -> str:
    """status を見て「結果」表示の日本語を返す.

    upload_failed の中でも「Submit 届いた可能性大」のときは「警告」と表現.
    """
    status = cycle_log.get("status", "unknown")
    if status == "upload_failed":
        up = cycle_log.get("phases", {}).get("upload", {}) or {}
        err = up.get("error", "")
        if _is_submit_likely_succeeded(err):
            return "警告: 結果取得不能 (Submit 届いた可能性大、要 eBay 履歴目視)"
    return _STATUS_JP.get(status, status)


def _format_sheet_label(cycle_log: Dict[str, Any]) -> str:
    """対象スプシの表示文字列を作る.

    sheet_id 単一指定 (= cron の通常運用) を最優先で判定し、HIGH / LOW を当てる。
    sheet_id 未指定の場合のみ sheet 引数 (high/low/both) で判定。
    """
    # 遅延 import (循環回避 + import コスト削減)
    try:
        from sheet_updater import HIGH_SHEET_ID, LOW_SHEET_ID  # noqa: PLC0415
    except Exception:
        HIGH_SHEET_ID = LOW_SHEET_ID = None

    sheet_id = cycle_log.get("sheet_id")
    if sheet_id:
        if sheet_id == HIGH_SHEET_ID:
            return "HIGH のみ"
        if sheet_id == LOW_SHEET_ID:
            return "LOW のみ"
        label = cycle_log.get("sheet_label") or "?"
        return f"単一スプシ ({label})"

    # sheet_id 未指定: sheet 引数 (high/low/both) で判定
    sheet_arg = cycle_log.get("sheet", "")
    return {
        "both": "HIGH + LOW 両方",
        "high": "HIGH のみ",
        "low":  "LOW のみ",
    }.get(sheet_arg, sheet_arg or "?")


def _format_body(cycle_log: Dict[str, Any]) -> str:
    """cycle_log を日本語の読みやすいレポートに整形."""
    lines = []
    status = cycle_log.get("status", "unknown")
    status_jp = _status_label(cycle_log)

    lines.append("=" * 50)
    lines.append("iMakInventory 巡回レポート")
    lines.append("=" * 50)
    lines.append(f"結果      : {status_jp}")
    lines.append(f"開始時刻   : {_fmt_ts(cycle_log.get('ts_start', ''))}")
    lines.append(f"終了時刻   : {_fmt_ts(cycle_log.get('ts_end', ''))}")
    lines.append(f"所要時間   : {_fmt_duration(cycle_log.get('ts_start', ''), cycle_log.get('ts_end', ''))}")
    lines.append(f"対象スプシ  : {_format_sheet_label(cycle_log)}")
    if cycle_log.get("test_mode"):
        lines.append("注意      : テストモード (本番運用ではない)")
    lines.append("")

    phases = cycle_log.get("phases", {}) or {}

    # 在庫監視 (monitor) — 一番大事なところ
    mon = phases.get("monitor", {}) or {}
    if mon:
        lines.append("【在庫監視】(仕入元サイトのページを巡回)")
        processed = mon.get("processed", 0) or 0
        errors = mon.get("errors", 0) or 0
        lines.append(f"  チェック件数  : {processed} 件")
        lines.append(f"  新規売切検知  : {mon.get('newly_sold', '?')} 件 ← eBay から取下げ対象")
        lines.append(f"  在庫復活検知  : {mon.get('newly_in_stock', '?')} 件")
        rate = (errors / processed) if processed else 0
        if errors == 0:
            lines.append("  通信エラー    : 0 件")
        elif rate >= 0.5:
            lines.append(f"  通信エラー    : {errors} 件 / {processed} 件中 ({rate*100:.0f}%) ★★ 異常高率、scraper or anti-bot 要確認")
        elif rate >= 0.1:
            lines.append(f"  通信エラー    : {errors} 件 / {processed} 件中 ({rate*100:.0f}%) ★ やや多い、傾向監視")
        else:
            lines.append(f"  通信エラー    : {errors} 件 (一時的、次 cycle で再試行)")
        lines.append("")

    # eBay 取下げ (revise + upload)
    rc = phases.get("revise_csv", {}) or {}
    up = phases.get("upload", {}) or {}
    if rc or up:
        lines.append("【eBay 取下げ】")
        if rc.get("skipped"):
            lines.append("  取下げ対象   : なし (新規売切なし)")
        elif rc:
            candidates = rc.get("candidates", 0) or 0
            allowed = rc.get("allowed", 0) or 0
            mon_newly_sold = mon.get("newly_sold", 0) or 0 if mon else 0
            excluded = mon_newly_sold - candidates
            if excluded > 0:
                lines.append(f"  CSV 生成     : {allowed} 件 (売切 {mon_newly_sold} 件中、item_id 空欄等で {excluded} 件除外)")
            else:
                lines.append(f"  CSV 生成     : {allowed} 件 (条件 OK で対象化)")
            deferred = rc.get("deferred", 0) or 0
            if deferred:
                lines.append(f"  保留         : {deferred} 件 (条件未達、次 cycle 持越)")

        if up.get("skipped"):
            # rc 側で既に「対象なし」表示済みなら upload 行は省略
            if not rc.get("skipped"):
                lines.append("  upload      : スキップ (取下げ対象が無いため)")
        elif up:
            success = up.get("success")
            csv_lines = up.get("csv_lines", "?")
            err_text = up.get("error", "")
            submit_likely_ok = _is_submit_likely_succeeded(err_text)
            if success:
                summary = _summarize_result_text(up.get("result_text", ""))
                lines.append(f"  upload結果   : 成功 ({csv_lines} 件処理) → {summary}")
            elif submit_likely_ok:
                # Submit は届いている可能性大、結果取得だけ失敗
                lines.append(f"  upload結果   : Submit OK / 結果取得失敗 ({csv_lines} 件、要 eBay 履歴目視)")
                lines.append(f"  失敗内容     : {_translate_error(err_text)}")
                if up.get("page_url"):
                    lines.append(f"  確認 URL     : {up['page_url']}")
            else:
                lines.append(f"  upload結果   : 失敗 ({csv_lines} 件未送信)")
                lines.append(f"  失敗内容     : {_translate_error(err_text)}")
                if up.get("page_url"):
                    lines.append(f"  確認 URL     : {up['page_url']}")
        lines.append("")

    # ヘルス (upload_health)
    uh = phases.get("upload_health", {}) or {}
    if uh:
        lines.append("【ヘルス】(連続失敗の検知)")
        nl = uh.get("not_logged_in_streak", 0) or 0
        fl = uh.get("flaky_streak", 0) or 0
        gn = uh.get("generic_failure_streak", 0) or 0
        # 「汎用エラー」の中身を直近 error から推定して詳細表示
        last_err = uh.get("last_failure_error") or up.get("error") or ""
        gn_detail = ""
        if gn > 0 and last_err:
            low = last_err.lower()
            if "result_csv_download_failed" in low:
                gn_detail = " (= 結果 CSV 取得 503 が継続)"
            elif "chrome not reachable" in low:
                gn_detail = " (= Chrome 起動失敗が継続)"
            else:
                gn_detail = f" (= {_translate_error(last_err)[:40]})"
        lines.append(f"  ログイン切れ : 連続 {nl} 回 {'← 即時アラート対象' if nl > 0 else '(正常)'}")
        lines.append(f"  判定不安定   : 連続 {fl} 回 {'← 3回でアラート' if fl >= 3 else ''}")
        lines.append(f"  汎用エラー   : 連続 {gn} 回{gn_detail} {'← 2回でアラート' if gn >= 2 else ''}")
        if uh.get("alert_fired"):
            lines.append(f"  → アラート発火 ({uh.get('reason', '')})")
        lines.append("")

    # 補助情報 (折りたたみ的扱い)
    aux = []
    pp = phases.get("pytest_precheck", {}) or {}
    if pp:
        aux.append(f"テスト事前実行 : {pp.get('status', '?')} ({pp.get('elapsed_sec', '?')}秒)")
    bk = phases.get("backup", {}) or {}
    for label, info in bk.items():
        if isinstance(info, dict):
            b = info.get("backup", {}) or {}
            aux.append(f"スプシ backup : {label} → {b.get('row_count', '?')} 行")
    aud = phases.get("audit_sample", {}) or {}
    for label, a in aud.items():
        if isinstance(a, dict):
            aux.append(f"抜取監査     : {label} → {a.get('appended', '?')} 件 audit タブに追記")
    if aux:
        lines.append("【補助】")
        for x in aux:
            lines.append(f"  {x}")
        lines.append("")

    # cycle 全体の例外
    if cycle_log.get("error"):
        lines.append("【巡回中に例外発生】")
        lines.append(f"  {_translate_error(cycle_log['error'])}")
        tb = cycle_log.get("traceback", "")
        if tb:
            lines.append("--- traceback (debug 用) ---")
            lines.append(tb[:1500])
        lines.append("")

    lines.append("=" * 50)
    lines.append("（このメールは iMakInventory が自動送信しています）")
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
        print(f"  [!] email_notifier: {msg}", file=sys.stderr)
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
