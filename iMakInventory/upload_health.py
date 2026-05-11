"""upload_health - eBay upload 健全性の監視 + 異常時の確実な通知.

事故 2026-05-05: inventory 専用 chrome profile の eBay session 切れに約 24 時間
気付かず 5 件の qty=0 化が未送信、Defect Rate 直撃事故の発生を受けて新設。

責務:
- 各 cycle の upload phase 結果を `decision_log/upload_health.json` に記録
- 異常時の通知を 3 経路で発火 (toast + デスクトップ ALERT ファイル + console)
- 通知強度は error 種別で分岐:
  - "not_logged_in" → **1 回目で即時通知** (= 真のログイン切れ、緊急、Defect Rate 直撃)
  - "upload result not detected" 等の flaky → 連続 3 回検知で通知
  - その他 success=False → 連続 2 回検知で通知

設計原則:
- 通知は **3 経路冗長**: toast 見逃し対策に必ずデスクトップにアラートファイルを作成
- 通知後はクールダウン無し (= 毎 cycle 失敗が続く間は毎回通知、無視されないため)
- success=True で streak リセット
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional


# ===========================================================================
# 設定
# ===========================================================================
SCRIPT_DIR = Path(__file__).resolve().parent
DECISION_LOG_DIR = SCRIPT_DIR / "decision_log"
HEALTH_FILE = DECISION_LOG_DIR / "upload_health.json"
DESKTOP_DIR = Path(os.environ.get("USERPROFILE", "")) / "OneDrive" / "デスクトップ"
DESKTOP_DIR_FALLBACK = Path(os.environ.get("USERPROFILE", "")) / "Desktop"

# 「即時通知」する error 種別 (1 回目で発火、substring match)
CRITICAL_ERRORS = {
    "not_logged_in",
    "session_expired",
    "session_expired_and_relogin_failed",
    # 2026-05-08 flaky 撲滅改造で追加:
    "result_not_in_history",   # eBay 履歴に出てこない = 真の未送信 (= ネット障害 / Submit 不達)
    "action_needed_failure",   # 写真要件 / invalid ItemID 等の手動対応必要 Failure (substring)
}

# 「連続検知」する error と発火閾値
FLAKY_THRESHOLD = 3   # 連続 3 回で通知 (popup 検出 false negative 等)
GENERIC_THRESHOLD = 2  # 連続 2 回で通知 (上記以外の失敗)


# ===========================================================================
# 状態の load / save
# ===========================================================================
def _load_health() -> dict:
    """upload_health.json をロード (なければ default)."""
    if not HEALTH_FILE.exists():
        return {
            "not_logged_in_streak": 0,
            "flaky_streak": 0,
            "generic_failure_streak": 0,
            "last_success_ts": None,
            "last_failure_ts": None,
            "last_failure_error": None,
            "last_alert_ts": None,
            "history": [],  # 直近 20 件保持
        }
    try:
        return json.loads(HEALTH_FILE.read_text(encoding="utf-8"))
    except Exception:
        # 壊れた health は捨てて再生成
        return {
            "not_logged_in_streak": 0,
            "flaky_streak": 0,
            "generic_failure_streak": 0,
            "last_success_ts": None,
            "last_failure_ts": None,
            "last_failure_error": None,
            "last_alert_ts": None,
            "history": [],
        }


def _save_health(health: dict) -> None:
    DECISION_LOG_DIR.mkdir(parents=True, exist_ok=True)
    HEALTH_FILE.write_text(
        json.dumps(health, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ===========================================================================
# error 種別に応じたアラート文言の生成
# ===========================================================================
def _critical_alert_message(error: str, csv_path: str, csv_lines: int,
                            cycle_ts: str, streak: int) -> tuple:
    """CRITICAL_ERRORS のうち、どの error 種別かで title / body を切替.

    Returns: (title, body)
    """
    err = (error or "").lower()
    common_footer = (
        f"\ncsv: {csv_path} ({csv_lines} 件未送信)\n"
        f"cycle_ts: {cycle_ts}\n"
    )

    if "session_expired" in err or "not_logged_in" in err or "not logged in" in err:
        title = f"⛔ iMakInventory: 真のログイン切れ ({streak} 回目)"
        body = (
            f"eBay 専用 chrome profile のセッションが切れました。\n"
            f"error: {error}"
            + common_footer
            + f"対応: control_panel で 'eBay 再ログイン' or "
              f"`python -m ebay_actions.sell_feed_uploader login`\n"
            + f"放置すると Defect Rate 直撃 (eBay で売れる → 仕入失敗 → キャンセル)。"
        )
    elif "action_needed_failure" in err:
        title = f"⚠️ iMakInventory: eBay 側で取下げ拒否 ({streak} 回目、要 listing 個別対応)"
        body = (
            f"eBay が listing 単体で取下げを拒否しました (画像要件 / Item Specifics 不備等)。\n"
            f"chrome profile のログインは生きてる可能性大、再ログインでは解消しません。\n"
            f"error: {error}"
            + common_footer
            + f"対応: cycle_log の failure_details で error_code を確認 → \n"
            + f"  ・該当 listing を eBay UI で手動 End Item\n"
            + f"  ・listing 単体の問題なので自動 retry では解決しない\n"
            + f"放置すると Defect Rate 直撃 (該当 item が売れる → 仕入失敗 → キャンセル)。"
        )
    elif "result_not_in_history" in err:
        title = f"⚠️ iMakInventory: eBay 履歴に upload 結果が出てこない ({streak} 回目)"
        body = (
            f"upload は submit したが eBay 履歴に表示されていない (ネット障害 / Submit 不達)。\n"
            f"error: {error}"
            + common_footer
            + f"対応: https://www.ebay.com/sh/reports/uploads を目視確認\n"
            + f"  ・履歴にあれば eBay 側は受理済 (= flaky 検出 false negative)\n"
            + f"  ・履歴になければ未送信、手動 upload 必要"
        )
    else:
        # 想定外の CRITICAL error: generic message
        title = f"⛔ iMakInventory: 重大エラー ({streak} 回目)"
        body = (
            f"upload phase で CRITICAL error が発生しました。\n"
            f"error: {error}"
            + common_footer
            + f"対応: cycle_log を確認して原因を特定してください。"
        )
    return title, body


# ===========================================================================
# 通知 (3 経路冗長)
# ===========================================================================
def _toast(title: str, body: str) -> None:
    """Windows toast (10 秒表示)."""
    try:
        from win10toast import ToastNotifier  # noqa: PLC0415
        ToastNotifier().show_toast(title, body, duration=10, threaded=True)
    except Exception:
        pass


def _desktop_alert_file(title: str, body: str, ts: str) -> Optional[Path]:
    """デスクトップにアラートファイル作成 (toast 見逃し対策)."""
    fname = f"ALERT_iMakInventory_{ts}.txt"
    for d in (DESKTOP_DIR, DESKTOP_DIR_FALLBACK):
        try:
            if d.parent.exists():
                d.mkdir(parents=True, exist_ok=True)
                path = d / fname
                path.write_text(
                    f"{title}\n{'='*60}\n{body}\n",
                    encoding="utf-8",
                )
                return path
        except Exception:
            continue
    return None


def _console_alert(title: str, body: str) -> None:
    """stdout に目立つ警告 (cycle log にも残る)."""
    bar = "!" * 60
    msg = f"\n{bar}\n!!! {title}\n{bar}\n{body}\n{bar}\n"
    try:
        print(msg, flush=True)
    except Exception:
        pass


def _fire_alert(title: str, body: str) -> dict:
    """3 経路で通知発火、結果を返す."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    _toast(title, body)
    desk_path = _desktop_alert_file(title, body, ts)
    _console_alert(title, body)
    return {
        "ts": ts,
        "title": title,
        "body": body,
        "desktop_alert": str(desk_path) if desk_path else None,
    }


# ===========================================================================
# upload phase 結果を判定 + 通知
# ===========================================================================
def record_upload_result(
    upload_result: dict,
    csv_path: Optional[str] = None,
    csv_lines: Optional[int] = None,
    cycle_ts: Optional[str] = None,
) -> dict:
    """upload phase の結果を upload_health.json に記録、必要なら通知発火.

    Args:
        upload_result: _phase_upload の戻り値 dict (success / error / popup_text 等)。
                       SKIPPED の場合は upload_result={"skipped": "..."} を渡す。
        csv_path:      対象 CSV パス
        csv_lines:     対象 CSV 行数
        cycle_ts:      cycle の起動 timestamp (ISO 8601)

    Returns: {"alert_fired": bool, "reason": str, "health": dict}
    """
    cycle_ts = cycle_ts or datetime.now().isoformat(timespec="seconds")
    health = _load_health()

    # SKIPPED は健全 (newly_sold=0 等で正常スキップ)、streak は変えない
    if "skipped" in upload_result:
        # 履歴記録のみ
        _push_history(health, {
            "ts": cycle_ts,
            "result": "skipped",
            "reason": upload_result.get("skipped"),
            "csv_lines": csv_lines,
        })
        _save_health(health)
        return {"alert_fired": False, "reason": "skipped", "health": health}

    success = bool(upload_result.get("success"))
    error = (upload_result.get("error") or "").strip()

    if success:
        # 成功 → 全 streak リセット
        health["not_logged_in_streak"] = 0
        health["flaky_streak"] = 0
        health["generic_failure_streak"] = 0
        health["last_success_ts"] = cycle_ts
        _push_history(health, {
            "ts": cycle_ts,
            "result": "success",
            "csv_path": csv_path,
            "csv_lines": csv_lines,
        })
        _save_health(health)
        return {"alert_fired": False, "reason": "success", "health": health}

    # 失敗 → error 種別で分類
    health["last_failure_ts"] = cycle_ts
    health["last_failure_error"] = error

    is_critical = any(c in error for c in CRITICAL_ERRORS)
    is_flaky = "upload result not detected" in error or "popup + history both inconclusive" in error

    alert_fired = False
    alert_reason = ""

    if is_critical:
        # 即時通知 (1 回目で発火)
        health["not_logged_in_streak"] += 1
        # error 種別で title / body / 対応文言を切替 (= 「ログイン切れ」誤誘導の防止)
        title, body = _critical_alert_message(
            error, csv_path, csv_lines, cycle_ts, health['not_logged_in_streak'])
        alert_info = _fire_alert(title, body)
        health["last_alert_ts"] = alert_info["ts"]
        alert_fired = True
        alert_reason = "critical_error_immediate"
        _push_history(health, {
            "ts": cycle_ts,
            "result": "failure_critical",
            "error": error,
            "csv_path": csv_path,
            "csv_lines": csv_lines,
            "alert": alert_info,
        })
    elif is_flaky:
        health["flaky_streak"] += 1
        if health["flaky_streak"] >= FLAKY_THRESHOLD:
            title = f"⚠️ iMakInventory: upload 検出 false negative {health['flaky_streak']} 回連続"
            body = (
                f"upload phase の popup/履歴検出が失敗 (= flaky の継続)。\n"
                f"eBay 側は受理されている可能性大だが、要 eBay 履歴目視確認。\n"
                f"error: {error}\n"
                f"csv: {csv_path} ({csv_lines} 件)\n"
                f"cycle_ts: {cycle_ts}\n"
                f"確認: https://www.ebay.com/sh/reports/uploads"
            )
            alert_info = _fire_alert(title, body)
            health["last_alert_ts"] = alert_info["ts"]
            alert_fired = True
            alert_reason = "flaky_streak_threshold"
        _push_history(health, {
            "ts": cycle_ts,
            "result": "failure_flaky",
            "error": error,
            "csv_path": csv_path,
            "csv_lines": csv_lines,
            "alert": alert_info if alert_fired else None,
        })
    else:
        health["generic_failure_streak"] += 1
        if health["generic_failure_streak"] >= GENERIC_THRESHOLD:
            title = f"⚠️ iMakInventory: upload 失敗 {health['generic_failure_streak']} 回連続"
            body = (
                f"upload phase が連続して失敗中。\n"
                f"error: {error}\n"
                f"csv: {csv_path} ({csv_lines} 件)\n"
                f"cycle_ts: {cycle_ts}"
            )
            alert_info = _fire_alert(title, body)
            health["last_alert_ts"] = alert_info["ts"]
            alert_fired = True
            alert_reason = "generic_failure_threshold"
        _push_history(health, {
            "ts": cycle_ts,
            "result": "failure_generic",
            "error": error,
            "csv_path": csv_path,
            "csv_lines": csv_lines,
            "alert": alert_info if alert_fired else None,
        })

    _save_health(health)
    return {"alert_fired": alert_fired, "reason": alert_reason, "health": health}


def _push_history(health: dict, entry: dict, max_keep: int = 20) -> None:
    """履歴に push、古い分は捨てる."""
    history = health.get("history") or []
    history.append(entry)
    if len(history) > max_keep:
        history = history[-max_keep:]
    health["history"] = history


# ===========================================================================
# 直近 cycle log を読んで health check (オプショナル使用)
# ===========================================================================
def assess_recent_cycles(n: int = 6) -> dict:
    """直近 N 個の cycle log を読んで「すべて upload skip or failure」が続いているか判定.

    通常運用 (HIGH cron 4h おき = 1 日 6 cycle) を意識した設計。
    1 日全部 SKIPPED 続き = 何かおかしい (出品増えてるのに 0 件はあり得ない) という
    別観点のチェックに使える。

    Returns: {"recent_n": int, "skipped": int, "success": int, "failure": int, "warn": bool}
    """
    import glob  # noqa: PLC0415
    files = sorted(glob.glob(str(DECISION_LOG_DIR / "cycle_*.jsonl")))[-n:]
    skipped = success = failure = 0
    for f in files:
        try:
            d = json.loads(Path(f).read_text(encoding="utf-8"))
            u = (d.get("phases") or {}).get("upload") or {}
            if "skipped" in u:
                skipped += 1
            elif u.get("success"):
                success += 1
            else:
                failure += 1
        except Exception:
            continue
    return {
        "recent_n": len(files),
        "skipped": skipped,
        "success": success,
        "failure": failure,
        "warn": failure >= 2 or (skipped == len(files) and len(files) >= n),
    }
