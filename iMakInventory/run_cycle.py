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
import sys
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from monitor_listings import process_sheet  # noqa: E402
from sheet_updater import HIGH_SHEET_ID, LOW_SHEET_ID  # noqa: E402
from ebay_actions.revise_csv_generator import run as run_revise_csv  # noqa: E402
from ebay_actions.sell_feed_uploader import upload_one_csv  # noqa: E402

DECISION_LOG_DIR = SCRIPT_DIR / "decision_log"
DECISION_LOG_DIR.mkdir(parents=True, exist_ok=True)
LOCK_FILE = DECISION_LOG_DIR / ".cycle.lock"
LOCK_STALE_HOURS = 6


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
                _log(f"⚠️ lock 保持中 (age {age/60:.1f} min < {LOCK_STALE_HOURS}h, content: {content})", test_mode)
                return False
            else:
                _log(f"⚠️ stale lock 検出 ({age/3600:.1f}h > {LOCK_STALE_HOURS}h)、削除して続行", test_mode)
                LOCK_FILE.unlink(missing_ok=True)
        except Exception as e:
            _log(f"⚠️ lock check 失敗: {e}", test_mode)
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
        _log(f"⚠️ lock release 失敗: {e}", test_mode)


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
# Phase wrappers
# ============================================================================
def _phase_monitor(sheet: str, limit: Optional[int], test_mode: bool) -> dict:
    """monitor_listings 経由で HIGH + LOW を処理."""
    _log(f"=== Phase 1/3: monitor_listings (sheet={sheet}, limit={limit}) ===", test_mode)
    targets = []
    if sheet in ("high", "both"):
        targets.append(("HIGH", HIGH_SHEET_ID))
    if sheet in ("low", "both"):
        targets.append(("LOW", LOW_SHEET_ID))
    grand = {"processed": 0, "newly_sold": 0, "newly_in_stock": 0, "errors": 0,
             "by_sheet": {}}
    for label, sid in targets:
        try:
            stats = process_sheet(
                sheet_id=sid, sheet_label=label,
                start_row=2, end_row=None, limit=limit,
                dry_run=False, sleep_sec=1,
            )
            grand["by_sheet"][label] = stats
            for k in ("processed", "newly_sold", "newly_in_stock", "errors"):
                grand[k] = grand[k] + stats.get(k, 0)
        except Exception as e:
            _log(f"  ❌ [{label}] 例外: {type(e).__name__}: {e}", test_mode)
            grand["by_sheet"][label] = {"error": f"{type(e).__name__}: {e}"}
    return grand


def _phase_revise_csv(sheet: str, test_mode: bool) -> dict:
    """revise_csv_generator (mode=pending) で CSV 生成."""
    _log(f"=== Phase 2/3: revise_csv_generator (sheet={sheet}, mode=pending) ===", test_mode)
    try:
        result = run_revise_csv(sheet=sheet, mode="pending", dry_run=False)
        return result
    except Exception as e:
        _log(f"  ❌ revise_csv 例外: {type(e).__name__}: {e}", test_mode)
        return {"error": f"{type(e).__name__}: {e}"}


def _phase_upload(csv_path_str: str, test_mode: bool) -> dict:
    """sell_feed_uploader.upload_one_csv で eBay FileExchange へ upload."""
    _log(f"=== Phase 3/3: sell_feed_uploader.upload (csv={csv_path_str}) ===", test_mode)
    try:
        result = upload_one_csv(Path(csv_path_str), dry_run=False)
        return result
    except Exception as e:
        _log(f"  ❌ upload 例外: {type(e).__name__}: {e}", test_mode)
        return {"error": f"{type(e).__name__}: {e}", "success": False}


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
) -> dict:
    cycle_log = {
        "ts_start": datetime.now().isoformat(timespec="seconds"),
        "test_mode": test_mode,
        "sheet": sheet,
        "limit": limit,
        "skip_upload": skip_upload,
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

    try:
        # Phase 1: monitor
        m = _phase_monitor(sheet, limit, test_mode)
        cycle_log["phases"]["monitor"] = m

        # Phase 2: revise CSV (skip if no newly_sold)
        if m.get("newly_sold", 0) == 0:
            _log(f"  newly_sold = 0 → revise CSV step skip", test_mode)
            cycle_log["phases"]["revise_csv"] = {"skipped": "no newly_sold"}
            cycle_log["phases"]["upload"] = {"skipped": "no csv"}
            cycle_log["status"] = "success_no_changes"
        else:
            r = _phase_revise_csv(sheet, test_mode)
            cycle_log["phases"]["revise_csv"] = r

            # Phase 3: upload
            csv_path = r.get("csv_path") if isinstance(r, dict) else None
            if not csv_path or skip_upload:
                _log(f"  upload skip (csv_path={csv_path}, skip_upload={skip_upload})", test_mode)
                cycle_log["phases"]["upload"] = {"skipped": "csv_path none or skip_upload"}
                cycle_log["status"] = "success_no_upload"
            else:
                u = _phase_upload(csv_path, test_mode)
                cycle_log["phases"]["upload"] = u
                if u.get("success"):
                    cycle_log["status"] = "success"
                else:
                    cycle_log["status"] = "upload_failed"
    except Exception as e:
        cycle_log["status"] = "error"
        cycle_log["error"] = f"{type(e).__name__}: {e}"
        cycle_log["traceback"] = traceback.format_exc()
        _log(f"  ❌ cycle 例外: {cycle_log['error']}", test_mode)
    finally:
        _release_lock(test_mode)
        cycle_log["ts_end"] = datetime.now().isoformat(timespec="seconds")

    log_path = _record_cycle_log(cycle_log)
    _log(f"=== cycle 完了: status={cycle_log['status']} log={log_path.name} ===", test_mode)

    # Toast
    monitor = cycle_log["phases"].get("monitor", {})
    summary = (
        f"sold={monitor.get('newly_sold', '?')} "
        f"in_stock={monitor.get('newly_in_stock', '?')} "
        f"errors={monitor.get('errors', '?')}"
    )
    if test_mode or cycle_log["status"] not in ("success", "success_no_changes"):
        title = f"iMakInventory: {cycle_log['status']}{' (TEST)' if test_mode else ''}"
        _notify_toast(title, summary)

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
    args = parser.parse_args()

    result = run_cycle(
        sheet=args.sheet,
        limit=args.limit,
        test_mode=args.test_mode,
        skip_upload=args.skip_upload,
    )
    print()
    print("=== final cycle_log ===")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
