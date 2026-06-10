"""run_cycle - 4h 自動巡回エントリポイント (Phase 5).

ワークフロー:
  1. lock file 確認 (decision_log/.cycle.lock)
  2. monitor_listings (HIGH + LOW 全件 or --limit) → スプシ D 列 + pending queue
  3. revise_csv_generator (mode=pending) → csv_output/revise_*.csv 生成
  4. sell_feed_uploader.upload_one_csv → eBay FileExchange へ upload
  5. cycle_<ts>.jsonl 記録 + Windows Toast 通知
  6. lock release

引数:
  --test-mode   : [TEST] ログ表記 + 完了時も通知発動
  --limit N     : monitor_listings の処理件数上限 (default 無制限)
  --skip-upload : upload step を skip (CSV 生成までで止める、検証用)
  --sheet       : "both" (default) / "high" / "low"
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

# stdout/stderr を UTF-8 に強制 (Windows pythonw 経由起動時に cp932 fallback で
# 絵文字 [OK]/[NG] 等が UnicodeEncodeError になるのを防ぐ)。
for _stream_name in ("stdout", "stderr"):
    _s = getattr(sys, _stream_name, None)
    if _s is not None and hasattr(_s, "reconfigure"):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass

from monitor_listings import process_sheet  # noqa: E402
from sheet_updater import (  # noqa: E402
    HIGH_SHEET_ID, LOW_SHEET_ID, open_sheet_by_id,
    get_listings_worksheet, read_listings_rows, LISTINGS_GID,
)
from ebay_actions.revise_csv_generator import (  # noqa: E402
    run as run_revise_csv,
    drain_pending_queue,
)
from ebay_actions.sell_feed_uploader import upload_one_csv  # noqa: E402 (= legacy fallback、 緊急時 手動 path)
from ebay_actions.trading_api_uploader import upload_csv_via_trading_api  # noqa: E402
from upload_health import record_upload_result  # noqa: E402
from ebay_actions.listing_verifier import verify_listings  # noqa: E402
from audit import sample_and_append as audit_sample_and_append  # noqa: E402
from backup import (  # noqa: E402
    backup_d_column, prune_old_backups, compute_d_diff, render_diff_md,
)
from progress import ProgressWriter, cleanup_stale_progress  # noqa: E402

DECISION_LOG_DIR = SCRIPT_DIR / "decision_log"
DECISION_LOG_DIR.mkdir(parents=True, exist_ok=True)
LOCK_FILE = DECISION_LOG_DIR / ".cycle.lock"
LOCK_STALE_HOURS = 6
PYTEST_PRECHECK_TIMEOUT_SEC = 120  # 検体 42 件は 1 秒程度、120s で十分

# Windows: 黒窓抑制用 flag (Phase 9 拡張 A2)
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def _patch_subprocess_no_window():
    """Windows: subprocess.Popen を monkey-patch して全子 process に CREATE_NO_WINDOW 強制.

    undetected_chromedriver は内部で subprocess.Popen 経由で chromedriver process を
    起動するが、creationflags を渡す手段がない。そのため Popen 自体を patch する。
    黒窓 (console window) 抑制が目的。GUI から起動された場合のみ実効、cron で
    pythonw.exe 起動なら冪等 (どちらも window 出ない)。
    """
    if sys.platform != "win32":
        return
    _orig_popen = subprocess.Popen
    if getattr(_orig_popen, "_imak_patched", False):
        return  # 二重 patch 防止 (re-import 時)

    no_window = subprocess.CREATE_NO_WINDOW

    class _PatchedPopen(_orig_popen):  # type: ignore[misc, valid-type]
        def __init__(self, *args, **kwargs):
            kwargs["creationflags"] = (kwargs.get("creationflags") or 0) | no_window
            super().__init__(*args, **kwargs)

    _PatchedPopen._imak_patched = True  # type: ignore[attr-defined]
    subprocess.Popen = _PatchedPopen  # type: ignore[misc]


_patch_subprocess_no_window()


# ============================================================================
# Logging
# ============================================================================
def _log(msg: str, test_mode: bool = False):
    prefix = "[TEST] " if test_mode else ""
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {prefix}{msg}"
    print(line, flush=True)


# ============================================================================
# Lock file
# ============================================================================
def _acquire_lock(test_mode: bool = False) -> bool:
    """Returns True if lock acquired. False if already held (and not stale)."""
    if LOCK_FILE.exists():
        try:
            age = time.time() - LOCK_FILE.stat().st_mtime
            if age < LOCK_STALE_HOURS * 3600:
                content = LOCK_FILE.read_text(encoding="utf-8", errors="replace")[:200]
                _log(f"[!] lock 保持中 (age {age/60:.1f} min < {LOCK_STALE_HOURS}h, content: {content})", test_mode)
                return False
            else:
                _log(f"[!] stale lock 検出 ({age/3600:.1f}h > {LOCK_STALE_HOURS}h)、削除して続行", test_mode)
                LOCK_FILE.unlink(missing_ok=True)
        except Exception as e:
            _log(f"[!] lock check 失敗: {e}", test_mode)
            return False
    LOCK_FILE.write_text(
        f"pid={os.getpid()} host={socket.gethostname()} ts={datetime.now().isoformat()}\n",
        encoding="utf-8",
    )
    return True


def _release_lock(test_mode: bool = False):
    try:
        LOCK_FILE.unlink(missing_ok=True)
    except Exception as e:
        _log(f"[!] lock release 失敗: {e}", test_mode)


# ============================================================================
# Toast notification (Windows)
# ============================================================================
def _notify_toast(title: str, body: str):
    """Windows toast 通知 (win10toast 未インストール時は黙って skip)."""
    try:
        from win10toast import ToastNotifier  # noqa: PLC0415
    except ImportError:
        return
    try:
        toaster = ToastNotifier()
        toaster.show_toast(title, body, duration=10, threaded=True)
    except Exception:
        pass


# ============================================================================
# Phase 7a: pytest precheck (offline marker)
# ============================================================================
def _phase_pytest_precheck(test_mode: bool) -> dict:
    """巡回開始前に offline 検体テスト 42 件を実行。失敗時は巡回中止 (fail-closed).

    Returns: {"status": "passed" | "failed" | "error", "stdout_tail", "stderr_tail", "elapsed"}
    DOM 仕様変更で検出ロジックが壊れていないか cycle 前に物理担保する。
    """
    _log("=== Phase 0/4: pytest precheck (offline 検体 42件) ===", test_mode)
    t0 = time.time()
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/", "-m", "offline", "-q",
             "--tb=short", "--no-header"],
            cwd=str(SCRIPT_DIR),
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=PYTEST_PRECHECK_TIMEOUT_SEC,
            creationflags=_NO_WINDOW,
        )
        elapsed = time.time() - t0
        if result.returncode == 0:
            _log(f"  [OK] pytest precheck pass ({elapsed:.1f}s)", test_mode)
            return {
                "status": "passed",
                "elapsed_sec": round(elapsed, 2),
                "stdout_tail": (result.stdout or "")[-500:],
            }
        else:
            _log(f"  [NG] pytest precheck FAILED rc={result.returncode} ({elapsed:.1f}s)", test_mode)
            return {
                "status": "failed",
                "returncode": result.returncode,
                "elapsed_sec": round(elapsed, 2),
                "stdout_tail": (result.stdout or "")[-1500:],
                "stderr_tail": (result.stderr or "")[-500:],
            }
    except subprocess.TimeoutExpired as e:
        return {"status": "error", "error": f"timeout {PYTEST_PRECHECK_TIMEOUT_SEC}s"}
    except Exception as e:
        return {"status": "error", "error": f"{type(e).__name__}: {e}"}


# ============================================================================
# Phase wrappers
# ============================================================================
def _phase_monitor(
    sheet: str, limit: Optional[int], test_mode: bool,
    single_sheet_id: Optional[str] = None,
    single_sheet_label: Optional[str] = None,
    high_sheet_id: Optional[str] = None,
    low_sheet_id: Optional[str] = None,
    progress_writer=None,
) -> dict:
    """monitor_listings 経由でスプシ処理 (HIGH/LOW セット or 単一)."""
    _log(f"=== Phase 1/3: monitor_listings (sheet={sheet}, limit={limit}) ===", test_mode)
    targets = []
    if single_sheet_id:
        # 単一スプシ mode (Phase 6a)
        targets.append((single_sheet_label or "SHEET", single_sheet_id))
    else:
        h_id = high_sheet_id or HIGH_SHEET_ID
        l_id = low_sheet_id or LOW_SHEET_ID
        if sheet in ("high", "both"):
            targets.append(("HIGH", h_id))
        if sheet in ("low", "both"):
            targets.append(("LOW", l_id))
    grand = {"processed": 0, "newly_sold": 0, "newly_in_stock": 0, "errors": 0,
             "url_alerts_count": 0, "by_sheet": {}, "error_rows": []}

    # ProgressWriter を monitor_listings の callback として食わせる
    progress_callback = None
    if progress_writer is not None:
        def progress_callback(**kwargs):  # noqa: E306
            progress_writer.update(**kwargs)

    for label, sid in targets:
        try:
            stats = process_sheet(
                sheet_id=sid, sheet_label=label,
                start_row=2, end_row=None, limit=limit,
                progress_callback=progress_callback,
                dry_run=False, sleep_sec=1,
            )
            grand["by_sheet"][label] = stats
            for k in ("processed", "newly_sold", "newly_in_stock", "errors"):
                grand[k] = grand[k] + stats.get(k, 0)
            grand["url_alerts_count"] += len(stats.get("url_alerts") or [])
            # error_rows を sheet 跨ぎで集約 (= 上位 20 件 / sheet × 2 sheet = 最大 40 件)
            for er in (stats.get("error_rows") or []):
                grand["error_rows"].append({**er, "sheet": label})
        except Exception as e:
            _log(f"  [NG] [{label}] 例外: {type(e).__name__}: {e}", test_mode)
            grand["by_sheet"][label] = {"error": f"{type(e).__name__}: {e}"}
    return grand


def _phase_revise_csv(
    sheet: str, test_mode: bool,
    single_sheet_id: Optional[str] = None,
    single_sheet_label: Optional[str] = None,
    high_sheet_id: Optional[str] = None,
    low_sheet_id: Optional[str] = None,
) -> dict:
    """revise_csv_generator (mode=pending) で CSV 生成."""
    _log(f"=== Phase 2/3: revise_csv_generator (sheet={sheet}, mode=pending) ===", test_mode)
    try:
        result = run_revise_csv(
            sheet=sheet, mode="pending", dry_run=False,
            high_sheet_id=high_sheet_id, low_sheet_id=low_sheet_id,
            single_sheet_id=single_sheet_id,
            single_sheet_label=single_sheet_label,
        )
        return result
    except Exception as e:
        _log(f"  [NG] revise_csv 例外: {type(e).__name__}: {e}", test_mode)
        return {"error": f"{type(e).__name__}: {e}"}


def _phase_audit_sample(
    targets: list,
    cycle_ts: str,
    test_mode: bool,
    n: int = 5,
) -> dict:
    """Phase 7d': IN_STOCK から 5 件 sample → audit シート append.

    targets: [(label, sheet_id), ...]
    """
    _log(f"=== Phase 4: audit sample (n={n} per sheet) ===", test_mode)
    results = {}
    seed = int(datetime.now().timestamp())
    for label, sid in targets:
        try:
            r = audit_sample_and_append(
                sheet_id=sid,
                sheet_label=label,
                decision_log_dir=DECISION_LOG_DIR,
                cycle_ts=cycle_ts,
                n=n,
                seed=seed,
            )
            _log(f"  [{label}] sampled={r['sampled']} appended={r['appended']}"
                 f"{' err=' + r['error'] if r.get('error') else ''}", test_mode)
            results[label] = r
        except Exception as e:
            _log(f"  [NG] [{label}] audit 例外: {type(e).__name__}: {e}", test_mode)
            results[label] = {"error": f"{type(e).__name__}: {e}"}
    return results


def _phase_upload(csv_path_str: str, test_mode: bool) -> dict:
    """Trading API ReviseInventoryStatus で qty 改訂 (= HQ 2026-06-03 指示).

    旧 path (= sell_feed_uploader / Selenium FileExchange UI) は緊急時 手動 fallback
    として import は残すが、 cycle phase からは直接呼ばない。
    Selenium path の脆さ (chromedriver DevTools 2GB JSONDecodeError 等) を回避し、
    OAuth token refresh + Trading API direct call で完結。
    """
    _log(f"=== Phase 3/3: trading_api_uploader.upload (csv={csv_path_str}) ===", test_mode)
    try:
        result = upload_csv_via_trading_api(Path(csv_path_str), dry_run=False)
        # 既存 cycle log schema 互換: success + error フィールド
        if not result.get("success"):
            result["error"] = (
                f"Trading API revise: total={result.get('total')} "
                f"ok={result.get('ok')} ng={result.get('ng')}"
            )
        return result
    except Exception as e:
        _log(f"  [NG] Trading API upload 例外: {type(e).__name__}: {e}", test_mode)
        return {"error": f"{type(e).__name__}: {e}", "success": False}


# ============================================================================
# Phase 8: D 列 backup / diff helpers
# ============================================================================
def _resolve_backup_targets(
    sheet: str,
    sheet_id: Optional[str],
    sheet_label: Optional[str],
    high_sheet_id: Optional[str],
    low_sheet_id: Optional[str],
) -> list:
    """backup 対象 [(label, sheet_id), ...] を返す.

    --sheet-id 単一指定 → [(sheet_label or "SHEET", sheet_id)]
    --sheet=both        → [("HIGH", high), ("LOW", low)]
    --sheet=high|low    → 片方のみ
    """
    if sheet_id:
        return [(sheet_label or "SHEET", sheet_id)]
    h_id = high_sheet_id or HIGH_SHEET_ID
    l_id = low_sheet_id or LOW_SHEET_ID
    targets = []
    if sheet in ("high", "both"):
        targets.append(("HIGH", h_id))
    if sheet in ("low", "both"):
        targets.append(("LOW", l_id))
    return targets


def _phase_compute_diff(
    cycle_ts: str,
    before_snapshot: dict,
    backup_targets: list,
    test_mode: bool,
) -> dict:
    """巡回前後の D 列差分を計算 → decision_log/diff_<cycle_ts>_<label>.md に出力.

    Returns: {sheet_label: {newly_sold, newly_in_stock, unchanged_count, md_path}}
    """
    summary = {}
    for label, sid in backup_targets:
        before = before_snapshot.get(label) or []
        if not before:
            summary[label] = {"skipped": "no_before_snapshot"}
            continue
        try:
            sh = open_sheet_by_id(sid)
            ws = get_listings_worksheet(sh, gid=LISTINGS_GID)
            after = read_listings_rows(ws, start_row=2, end_row=None, only_with_url=False)
            diff = compute_d_diff(before, after)
            md = render_diff_md(diff, sheet_label=label, cycle_ts=cycle_ts)
            md_path = DECISION_LOG_DIR / f"diff_{cycle_ts}_{label}.md"
            md_path.write_text(md, encoding="utf-8")
            n_sold = len(diff["newly_sold"])
            n_back = len(diff["newly_in_stock"])
            _log(
                f"  D 列差分 [{label}]: newly_sold={n_sold} / newly_in_stock={n_back} "
                f"→ {md_path.name}",
                test_mode,
            )
            summary[label] = {
                "newly_sold": n_sold,
                "newly_in_stock": n_back,
                "unchanged_count": diff["unchanged_count"],
                "md_path": str(md_path),
            }
        except Exception as e:
            summary[label] = {"error": f"{type(e).__name__}: {e}"}
    return summary


# ============================================================================
# cycle_<ts>.jsonl 記録
# ============================================================================
def _record_cycle_log(cycle_log: dict) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = DECISION_LOG_DIR / f"cycle_{ts}.jsonl"
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps(cycle_log, ensure_ascii=False, indent=2))
    return path


# ============================================================================
# Main
# ============================================================================
def run_cycle(
    sheet: str = "both",
    limit: Optional[int] = None,
    test_mode: bool = False,
    skip_upload: bool = False,
    monitor_only: bool = False,
    sheet_id: Optional[str] = None,
    sheet_label: Optional[str] = None,
    high_sheet_id: Optional[str] = None,
    low_sheet_id: Optional[str] = None,
) -> dict:
    cycle_log = {
        "ts_start": datetime.now().isoformat(timespec="seconds"),
        "test_mode": test_mode,
        "sheet": sheet,
        "sheet_id": sheet_id,
        "sheet_label": sheet_label,
        "limit": limit,
        "skip_upload": skip_upload,
        "monitor_only": monitor_only,
        "phases": {},
        "status": "init",
    }

    if not _acquire_lock(test_mode):
        cycle_log["status"] = "skipped_lock_held"
        cycle_log["ts_end"] = datetime.now().isoformat(timespec="seconds")
        path = _record_cycle_log(cycle_log)
        _notify_toast("iMakInventory: skipped",
                      f"lock 保持中、巡回 skip ({path.name})")
        return cycle_log

    # ライブ進捗 writer (Phase 9b: GUI が 30秒 polling して表示)
    cleanup_stale_progress()  # default: 30 分以上古いものを削除
    cycle_ts_compact = cycle_log["ts_start"].replace("-", "").replace(":", "").replace("T", "_")[:15]
    progress_writer = ProgressWriter(cycle_ts=cycle_ts_compact)

    try:
        progress_writer.update(phase="pytest_precheck", force=True)
        # Phase 0: pytest precheck (Phase 7a) — 検体 DOM 仕様変更を検知して fail-closed
        precheck = _phase_pytest_precheck(test_mode)
        cycle_log["phases"]["pytest_precheck"] = precheck
        if precheck["status"] != "passed":
            cycle_log["status"] = "aborted_pytest_precheck_failed"
            _notify_toast(
                "iMakInventory 巡回中止",
                f"pytest 検体 失敗 = 仕様変更の可能性 (status={precheck['status']})。"
                f"巡回 skip、検体追加 / scraper 修正 が必要。"
            )
            return cycle_log  # finally で lock release される

        # Phase 0.5: listing verifier (Phase 7e) — 前回 upload の eBay 反映確認 (4h ずらし)
        progress_writer.update(phase="listing_verify", force=True)
        try:
            _log("=== Phase 0.5/4: listing_verifier (前回 upload を verify) ===", test_mode)
            verify_summary = verify_listings()
            cycle_log["phases"]["listing_verify"] = {
                "input_item_count": verify_summary.get("input_item_count", 0),
                "new_item_count": verify_summary.get("new_item_count", 0),
                "alerts_count": len(verify_summary.get("alerts", [])),
                "decision_log_path": verify_summary.get("decision_log_path"),
                "error": verify_summary.get("error"),
            }
            if verify_summary.get("alerts"):
                _log(f"  [!] verify alert: {len(verify_summary['alerts'])} 件 qty != 0", test_mode)
                _notify_toast(
                    "iMakInventory verify ALERT",
                    f"前回 upload {len(verify_summary['alerts'])} 件で qty != 0 (取下げ失敗?)。"
                    f"decision_log/verify_*.jsonl 確認"
                )
        except Exception as e:
            _log(f"  [!] verify 例外 (続行): {type(e).__name__}: {e}", test_mode)
            cycle_log["phases"]["listing_verify"] = {"error": f"{type(e).__name__}: {e}"}

        # Phase 0.7: D 列バックアップ + 古い backup 削除 (Phase 8a)
        progress_writer.update(phase="backup", force=True)
        cycle_ts = cycle_log["ts_start"].replace("-", "").replace(":", "").replace("T", "_")[:15]
        backup_targets = _resolve_backup_targets(
            sheet, sheet_id, sheet_label, high_sheet_id, low_sheet_id,
        )
        backup_results = {}
        before_snapshot = {}  # {sheet_label: [rows]} 差分計算用
        for label, sid in backup_targets:
            try:
                _log(f"=== Phase 0.7/4: backup_d_column [{label}] ===", test_mode)
                sh = open_sheet_by_id(sid)
                # 差分用に backup 直前の D 列を memory に保持
                ws = get_listings_worksheet(sh, gid=LISTINGS_GID)
                before_snapshot[label] = read_listings_rows(
                    ws, start_row=2, end_row=None, only_with_url=False,
                )
                br = backup_d_column(sh, cycle_ts=cycle_ts)
                pr = prune_old_backups(sh)
                backup_results[label] = {"backup": br, "prune": pr}
                if br.get("error"):
                    _log(f"  [!] backup 失敗 [{label}]: {br['error']}", test_mode)
                else:
                    _log(
                        f"  [OK] backup 完了 [{label}]: tab={br['backup_tab_name']} "
                        f"rows={br['row_count']} prune.deleted={pr['deleted']}",
                        test_mode,
                    )
            except Exception as e:
                _log(f"  [!] backup 例外 (続行) [{label}]: {type(e).__name__}: {e}", test_mode)
                backup_results[label] = {"error": f"{type(e).__name__}: {e}"}
        cycle_log["phases"]["backup"] = backup_results

        # Phase 1: monitor
        progress_writer.update(phase="monitor", force=True)
        m = _phase_monitor(
            sheet, limit, test_mode,
            single_sheet_id=sheet_id,
            single_sheet_label=sheet_label,
            high_sheet_id=high_sheet_id,
            low_sheet_id=low_sheet_id,
            progress_writer=progress_writer,
        )
        cycle_log["phases"]["monitor"] = m

        # Phase 1.5: D 列差分 → diff_<cycle_ts>.md (Phase 8b)
        progress_writer.update(phase="d_diff", force=True)
        try:
            diff_summary = _phase_compute_diff(
                cycle_ts, before_snapshot, backup_targets, test_mode,
            )
            cycle_log["phases"]["d_diff"] = diff_summary
        except Exception as e:
            _log(f"  [!] diff 計算例外 (続行): {type(e).__name__}: {e}", test_mode)
            cycle_log["phases"]["d_diff"] = {"error": f"{type(e).__name__}: {e}"}

        # Phase 2: revise CSV
        progress_writer.update(phase="revise_csv", force=True)
        if monitor_only:
            _log(f"  --monitor-only mode → revise CSV / upload 共に skip", test_mode)
            cycle_log["phases"]["revise_csv"] = {"skipped": "monitor_only"}
            cycle_log["phases"]["upload"] = {"skipped": "monitor_only"}
            cycle_log["status"] = "success_monitor_only"
        elif m.get("newly_sold", 0) == 0:
            _log(f"  newly_sold = 0 → revise CSV step skip", test_mode)
            cycle_log["phases"]["revise_csv"] = {"skipped": "no newly_sold"}
            cycle_log["phases"]["upload"] = {"skipped": "no csv"}
            cycle_log["status"] = "success_no_changes"
        else:
            r = _phase_revise_csv(
                sheet, test_mode,
                single_sheet_id=sheet_id,
                single_sheet_label=sheet_label,
                high_sheet_id=high_sheet_id,
                low_sheet_id=low_sheet_id,
            )
            cycle_log["phases"]["revise_csv"] = r

            # Phase 3: upload
            progress_writer.update(phase="upload", force=True)
            csv_path = r.get("csv_path") if isinstance(r, dict) else None
            csv_lines_for_health = (r.get("allowed") if isinstance(r, dict) else None)
            if not csv_path or skip_upload:
                _log(f"  upload skip (csv_path={csv_path}, skip_upload={skip_upload})", test_mode)
                cycle_log["phases"]["upload"] = {"skipped": "csv_path none or skip_upload"}
                cycle_log["status"] = "success_no_upload"
                # health: skipped 記録 (streak 変えず履歴のみ)
                try:
                    record_upload_result(
                        cycle_log["phases"]["upload"],
                        csv_path=csv_path, csv_lines=csv_lines_for_health,
                        cycle_ts=cycle_log["ts_start"],
                    )
                except Exception as e:
                    _log(f"  [!] upload_health record 失敗 (skipped path): {type(e).__name__}: {e}", test_mode)
            else:
                u = _phase_upload(csv_path, test_mode)
                cycle_log["phases"]["upload"] = u
                if u.get("success"):
                    cycle_log["status"] = "success"
                else:
                    cycle_log["status"] = "upload_failed"
                # pending → processed drain (= upload 成功 item のみ)。
                # Phase 2 (CSV 生成) で drain せず ここで drain することで、
                # transient 失敗 (DNS/Timeout 等) の item を pending に残し
                # 次 cycle で自動 retry させる。 success には safe_failure
                # (= eBay 上で 既 ended) も含む (= trading_api_uploader 内で
                # success=True 化済)。
                if r.get("mode") == "pending":
                    successful_ids = [
                        res["item_id"]
                        for res in (u.get("results") or [])
                        if res.get("success")
                    ]
                    try:
                        moved = drain_pending_queue(successful_ids)
                        failed_kept = len(r.get("allowed_item_ids") or []) - len(successful_ids)
                        _log(f"  pending → processed archive: {moved} 件 "
                             f"(失敗 {failed_kept} 件は pending 残置 → 次 cycle で retry)",
                             test_mode)
                    except Exception as e:
                        _log(f"  [!] drain_pending_queue 失敗: {type(e).__name__}: {e}",
                             test_mode)
                # HQ 2026-06-10 FINAL 指示 B: upload で in-cycle verify NG (= qty>0 残存)
                # の item を action_required.jsonl に記録 (= cycle report で「要対応 Y 件」 表示)
                try:
                    from monitor_listings import append_action_required  # noqa: PLC0415
                    verify_failed = [
                        res for res in (u.get("results") or [])
                        if not res.get("success") and res.get("verified") is False
                        and res.get("verify_qty") not in (None, 0)
                    ]
                    for res in verify_failed:
                        append_action_required(
                            sheet_label=res.get("sheet_label", ""),
                            result={
                                "row_index": res.get("row_index", -1),
                                "url":       res.get("url", ""),
                                "item_id":   res.get("item_id", ""),
                                "title":     res.get("title", ""),
                                "supplier":  res.get("supplier", ""),
                                "raw_status": "verify_qty_gt0",
                            },
                            reason="verify_qty_gt0_giveup",
                            dry_run=False,
                        )
                    if verify_failed:
                        _log(f"  [★要対応] in-cycle verify 通過せず: {len(verify_failed)} 件 → action_required.jsonl",
                             test_mode)
                except Exception as e:
                    _log(f"  [!] action_required 記録失敗: {type(e).__name__}: {e}",
                         test_mode)
                # health: 成否を記録 + 必要なら通知発火 (3 経路冗長)
                try:
                    health_res = record_upload_result(
                        u, csv_path=csv_path, csv_lines=csv_lines_for_health,
                        cycle_ts=cycle_log["ts_start"],
                    )
                    cycle_log["phases"]["upload_health"] = {
                        "alert_fired": health_res.get("alert_fired"),
                        "reason": health_res.get("reason"),
                        "not_logged_in_streak": health_res["health"].get("not_logged_in_streak"),
                        "flaky_streak": health_res["health"].get("flaky_streak"),
                        "generic_failure_streak": health_res["health"].get("generic_failure_streak"),
                    }
                    if health_res.get("alert_fired"):
                        _log(f"  [ALERT] upload_health ALERT 発火 (reason={health_res.get('reason')})", test_mode)
                except Exception as e:
                    _log(f"  [!] upload_health record 失敗: {type(e).__name__}: {e}", test_mode)

        # Phase 4: audit sample (Phase 7d') — IN_STOCK から 5 件抜き取り → audit シート追記
        # cycle status に関わらず実行 (in_stock データがあれば audit する)
        progress_writer.update(phase="audit_sample", force=True)
        try:
            audit_targets = []
            if sheet_id:
                audit_targets.append((sheet_label or "SHEET", sheet_id))
            else:
                h_id = high_sheet_id or HIGH_SHEET_ID
                l_id = low_sheet_id or LOW_SHEET_ID
                if sheet in ("high", "both"):
                    audit_targets.append(("HIGH", h_id))
                if sheet in ("low", "both"):
                    audit_targets.append(("LOW", l_id))
            audit_result = _phase_audit_sample(
                audit_targets,
                cycle_ts=cycle_log["ts_start"][:16].replace("T", " "),
                test_mode=test_mode,
                n=5,
            )
            cycle_log["phases"]["audit_sample"] = audit_result
        except Exception as e:
            _log(f"  [NG] audit sample 例外: {type(e).__name__}: {e}", test_mode)
            cycle_log["phases"]["audit_sample"] = {"error": f"{type(e).__name__}: {e}"}

        # Phase 5: reverse_audit (= 意図 D=○ vs 実 eBay qty>0 reconciliation)
        # HQ 2026-06-10 confirm 指示 B 準拠:
        # - 「再発しないこと」 の唯一の客観証拠 (= 継続乖離 0 件)
        # - 初回は 5 週間分の既存乖離が出るのが正常 = audit が動作してる証拠
        # - 09:30 `--sheet both` cycle のみ実行 (= 4h 単一 cycle ではコスト/API quota 考慮)
        # - read-only 突合 + alert のみ、 auto-fix は Phase 2 で別検討
        should_run_audit = (sheet == "both" and not sheet_id and not monitor_only)
        if should_run_audit:
            progress_writer.update(phase="reverse_audit", force=True)
            _log(f"=== Phase 5: reverse_audit (= D=○ vs eBay qty>0 突合) ===", test_mode)
            # eBay active map は両 audit で共有 (= 全件 DL を 1 回に集約、 二重 DL 回避)
            shared_qty_map = None
            try:
                from reverse_audit import _fetch_ebay_qty_map  # noqa: PLC0415
                shared_qty_map = _fetch_ebay_qty_map()
                _log(f"  eBay active map: {len(shared_qty_map)} 件 (両 audit で共有)", test_mode)
            except Exception as e:
                _log(f"  [!] eBay active map 取得失敗、 audit は各自 fetch に fallback: {type(e).__name__}: {e}", test_mode)
                shared_qty_map = None
            try:
                from reverse_audit import run_reverse_audit  # noqa: PLC0415
                ra_result = run_reverse_audit(
                    high_sheet_id=high_sheet_id,
                    low_sheet_id=low_sheet_id,
                    write_log=True,
                    qty_map=shared_qty_map,
                )
                cycle_log["phases"]["reverse_audit"] = ra_result
                # 乖離検出時の alert (HQ 条件 B 文言: 「初回 = 既存乖離鳥瞰、 fail-OPEN 隠ぺい禁止」)
                mc = ra_result.get("mismatch_count", 0)
                if mc > 0:
                    _log(f"  [★critical] reverse_audit 乖離 {mc} 件検出", test_mode)
                    _log(f"      初回実行は既存乖離の鳥瞰= audit が機能してる証拠。",
                         test_mode)
                    _log(f"      log: {ra_result.get('log_path')}", test_mode)
                elif mc == 0:
                    _log(f"  ✓ reverse_audit 乖離 0 件 (= 継続証跡を 1 件積上げ)",
                         test_mode)
                elif mc == -1:
                    _log(f"  [!] reverse_audit 中断: {ra_result.get('error')}",
                         test_mode)
            except Exception as e:
                _log(f"  [NG] reverse_audit 例外: {type(e).__name__}: {e}", test_mode)
                cycle_log["phases"]["reverse_audit"] = {
                    "error": f"{type(e).__name__}: {e}",
                }

            # Phase 5b: ebay_down_audit (= 逆方向 #2、 D 空欄 + eBay qty=0/ended)
            # user 指示 2026-06-10: eBay が勝手に / 手動で取下げ → eBay は qty=0 or ended
            # だが sheet D 未売切 のものを 「在庫あり・eBay取下げ済」 review シートに書出。
            # D 列は触らない (= 書き出すだけ、 自動売切化しない)。 reverse_audit の鏡像。
            progress_writer.update(phase="ebay_down_audit", force=True)
            _log(f"=== Phase 5b: ebay_down_audit (= D空欄 vs eBay qty=0/ended 突合) ===", test_mode)
            try:
                from reverse_audit import run_ebay_down_sheet_active_audit  # noqa: PLC0415
                ed_result = run_ebay_down_sheet_active_audit(
                    high_sheet_id=high_sheet_id,
                    low_sheet_id=low_sheet_id,
                    write_sheet=True,
                    write_log=True,
                    qty_map=shared_qty_map,
                )
                cycle_log["phases"]["ebay_down_audit"] = ed_result
                oc = ed_result.get("orphan_count", 0)
                if oc > 0:
                    _log(f"  [info] ebay_down orphan {oc} 件 → review シート更新 "
                         f"{ed_result.get('by_state')} (coverage {ed_result.get('coverage')})",
                         test_mode)
                elif oc == 0:
                    _log(f"  ✓ ebay_down orphan 0 件", test_mode)
                elif oc == -1:
                    _log(f"  [!] ebay_down_audit 中断: {ed_result.get('error')}", test_mode)
            except Exception as e:
                _log(f"  [NG] ebay_down_audit 例外: {type(e).__name__}: {e}", test_mode)
                cycle_log["phases"]["ebay_down_audit"] = {
                    "error": f"{type(e).__name__}: {e}",
                }
        else:
            _log(f"  reverse_audit skip (= 4h 単一 cycle、 09:30 両 sheet cycle で実行)",
                 test_mode)
    except Exception as e:
        cycle_log["status"] = "error"
        cycle_log["error"] = f"{type(e).__name__}: {e}"
        cycle_log["traceback"] = traceback.format_exc()
        _log(f"  [NG] cycle 例外: {cycle_log['error']}", test_mode)
    finally:
        _release_lock(test_mode)
        cycle_log["ts_end"] = datetime.now().isoformat(timespec="seconds")
        # ライブ進捗ファイルを片付け (GUI が「待機中」表示に戻る)
        try:
            progress_writer.finalize()
        except Exception:
            pass

    # HQ 2026-06-10 FINAL 指示 B/C: action_required 集計を cycle_log に格納
    # → email_notifier が冒頭 「⚠️ 要対応 Y件」 or 「✅ 全件取下げ完了」 ヘッダ描画に利用
    try:
        action_file = Path(__file__).resolve().parent / "decision_log" / "action_required.jsonl"
        cycle_action_count = 0
        cycle_action_items = []
        cycle_start = cycle_log.get("ts_start", "")
        if action_file.exists() and cycle_start:
            for line in action_file.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                if entry.get("ts", "") >= cycle_start:
                    cycle_action_count += 1
                    cycle_action_items.append({
                        "sheet":    entry.get("sheet", ""),
                        "row":      entry.get("row_index", -1),
                        "item_id":  entry.get("item_id", ""),
                        "title":    (entry.get("title") or "")[:50],
                        "reason":   entry.get("reason", ""),
                    })
        cycle_log["phases"]["action_required_summary"] = {
            "count": cycle_action_count,
            "items": cycle_action_items[:20],  # メール表示用に上位 20 件
        }
    except Exception as e:
        _log(f"  [!] action_required 集計失敗: {type(e).__name__}: {e}", test_mode)

    log_path = _record_cycle_log(cycle_log)
    _log(f"=== cycle 完了: status={cycle_log['status']} log={log_path.name} ===", test_mode)

    # Toast
    monitor = cycle_log["phases"].get("monitor", {})
    d_diff = cycle_log["phases"].get("d_diff", {}) or {}
    diff_sold = sum(
        v.get("newly_sold", 0) for v in d_diff.values() if isinstance(v, dict)
    )
    diff_back = sum(
        v.get("newly_in_stock", 0) for v in d_diff.values() if isinstance(v, dict)
    )
    summary = (
        f"sold={monitor.get('newly_sold', '?')} "
        f"in_stock={monitor.get('newly_in_stock', '?')} "
        f"errors={monitor.get('errors', '?')}"
        f" | D差分: ○化={diff_sold} 復活={diff_back}"
    )
    if test_mode or cycle_log["status"] not in ("success", "success_no_changes"):
        title = f"iMakInventory: {cycle_log['status']}{' (TEST)' if test_mode else ''}"
        _notify_toast(title, summary)

    # cycle 完了メール送信 (opt-in: encrypted_gmail.dat が無ければ skip)
    # fail-safe: 送信失敗しても cycle 全体を落とさない
    # ユーザー指示 2026-06-10 「放置禁止」: email 失敗 = silent 化 risk。
    # 2 段 fallback: 1) 通常 email、 失敗 → 2) 最小 fallback email + desktop toast
    mail_sent = False
    try:
        from email_notifier import send_cycle_report  # noqa: PLC0415
        mail_res = send_cycle_report(cycle_log)
        if mail_res.get("sent"):
            _log("  [mail] cycle report mail 送信完了", test_mode)
            mail_sent = True
        elif mail_res.get("error"):
            _log(f"  [!] cycle report mail 失敗: {mail_res['error']}", test_mode)
        # skipped_reason のみ (= opt-in 未有効化) は無音 (毎 cycle ログ汚染防止)
        elif mail_res.get("skipped_reason"):
            mail_sent = True  # opt-in 未有効化は silent 化 risk ではない
    except Exception as e:
        _log(f"  [!] email_notifier 例外: {type(e).__name__}: {e}", test_mode)

    # email 失敗時の最終手段: desktop toast + ファイル alert (= silent 化を絶対回避)
    if not mail_sent:
        try:
            ar_count = (cycle_log.get("phases", {})
                          .get("action_required_summary", {}) or {}).get("count", 0)
            status = cycle_log.get("status", "?")
            title = "[★iMakInventory] email 送信失敗、 cycle 結果未通知"
            body = (
                f"status={status} action_required={ar_count}\n"
                f"ts_start={cycle_log.get('ts_start','?')}\n"
                f"ts_end={cycle_log.get('ts_end','?')}\n"
                f"\n★ ユーザー指示 「放置禁止」 違反 risk: メール経路全断、 cycle 結果を見落とすリスクあり。\n"
                f"対応: logs/cycle_{cycle_log.get('ts_start','')[:13].replace('T','_')}*.jsonl を chk\n"
            )
            _notify_toast(title, body[:200])
            # 物理ファイル alert (= desktop 通知も失敗時の最終 fallback)
            try:
                desk = Path.home() / "OneDrive" / "デスクトップ" / f"ALERT_iMakInventory_mail_failed_{cycle_log.get('ts_start','')[:13].replace(':','').replace('T','_')}.txt"
                desk.write_text(title + "\n\n" + body, encoding="utf-8")
                _log(f"  [!] mail 失敗 → desktop alert file 出力: {desk.name}", test_mode)
            except Exception as e2:
                _log(f"  [!] mail 失敗 + desktop alert 失敗: {type(e2).__name__}: {e2}", test_mode)
        except Exception as e3:
            _log(f"  [!] mail 失敗 fallback 自体も失敗: {type(e3).__name__}: {e3}", test_mode)

    return cycle_log


def main():
    parser = argparse.ArgumentParser(description="iMakInventory 4h 自動巡回 (Phase 5)")
    parser.add_argument("--sheet", choices=["high", "low", "both"], default="both")
    parser.add_argument("--limit", type=int, default=None,
                        help="monitor 処理件数上限 (default 無制限)")
    parser.add_argument("--test-mode", action="store_true",
                        help="[TEST] ログ + 完了通知発動")
    parser.add_argument("--skip-upload", action="store_true",
                        help="upload step skip (CSV 生成までで止める)")
    parser.add_argument("--monitor-only", action="store_true",
                        help="在庫チェックのみ (CSV 生成も upload も skip、audit は実行)")
    # Phase 6a: 単一スプシ mode + ID 上書き
    parser.add_argument("--sheet-id", default=None,
                        help="単一スプシ mode: 指定 ID のみ処理 "
                             "(--high-sheet-id/--low-sheet-id と排他)")
    parser.add_argument("--sheet-label", default="SHEET",
                        help="--sheet-id 使用時のラベル (default: SHEET)")
    parser.add_argument("--high-sheet-id", default=os.environ.get("INVENTORY_HIGH_SHEET_ID"),
                        help="HIGH 用 spreadsheet ID 上書き (env: INVENTORY_HIGH_SHEET_ID)")
    parser.add_argument("--low-sheet-id", default=os.environ.get("INVENTORY_LOW_SHEET_ID"),
                        help="LOW 用 spreadsheet ID 上書き (env: INVENTORY_LOW_SHEET_ID)")
    args = parser.parse_args()

    if args.sheet_id and (args.high_sheet_id or args.low_sheet_id):
        print("[NG] --sheet-id と --high-sheet-id/--low-sheet-id は併用不可")
        sys.exit(2)

    result = run_cycle(
        sheet=args.sheet,
        limit=args.limit,
        test_mode=args.test_mode,
        skip_upload=args.skip_upload,
        monitor_only=args.monitor_only,
        sheet_id=args.sheet_id,
        sheet_label=args.sheet_label,
        high_sheet_id=args.high_sheet_id,
        low_sheet_id=args.low_sheet_id,
    )
    print()
    print("=== final cycle_log ===")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
