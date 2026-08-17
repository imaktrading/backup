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
import re
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
from ebay_actions.revive_csv_generator import (  # noqa: E402
    run as run_revive_csv,
    drain_pending_revive,
    PENDING_REVIVE_FILE,
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

# 巡回停止の非-silent 検知 + 自己回復 (2026-07-27):
# HIGH の所要が 60〜64 分に伸び、LOW 起動 (HIGH 開始 +60 分) と衝突して skipped_lock_held が
# 3 連続 → LOW が 25h 止まっていたのを実観測 (toast だけで誰も気づけない = silent)。
#   ① lock 保持中でも即諦めず LOCK_WAIT_MINUTES まで解放を待って自己回復する
#   ② 「最後に完走してからの経過」が想定間隔を大きく超えたら desktop file + mail で非-silent 告知
#      (skip 時だけでなく毎 cycle 末に全 label を突合 = 「そもそも task が発火しない」も検知できる)
LOCK_WAIT_MINUTES = 45          # lock 解放待ちの上限 (次 cycle を潰さない範囲)
LOCK_WAIT_POLL_SEC = 60
CYCLE_INTERVAL_HOURS = {"SHEET": 4, "LOW": 8}   # 各 label の巡回間隔 (Task Scheduler と対)
CYCLE_STALE_MULT = 2.2                          # この倍率を超えたら「止まっている」
CYCLE_STALE_ALERT_STATE = DECISION_LOG_DIR / "cycle_staleness_alert_state.json"
CYCLE_STALE_ALERT_THROTTLE_HOURS = 6            # 同 label の再告知間隔 (アラート疲労防止)

# eBay Trading API 日次呼出量の事前警告 (2026-07-28):
# 2026-07-04 に 518 (Call usage limit reached) で取下げ upload 全滅 → 取下げ漏れ 24 件蓄積。
# 上限に当たってから気づくのでは遅いので、消費量を計測し 70% で 1 日 1 回だけ非-silent 告知する。
EBAY_API_DAILY_LIMIT = 5000                     # eBay Trading API の既定 日次上限
EBAY_API_WARN_RATIO = 0.7
EBAY_API_ALERT_STATE = DECISION_LOG_DIR / "ebay_api_alert_state.json"

# 補URL消込 急増ガード ALERT の throttle (2026-07-25):
# 既知 backlog (snkrdunk判定復旧待ち等) で毎 cycle HOLD すると desktop file+mail を 4h毎に量産し
# アラート疲労 (2026-07-25 デスクトップに3件/日堆積で発覚)。cycle ログ/レポートには毎回出す
# (= 非 silent 維持) が、desktop file+mail は「新規/悪化/24h経過」時のみに絞る (reverse_audit OK_ACK_ONLY 思想)。
BACKUP_CLEAR_ALERT_STATE = DECISION_LOG_DIR / "backup_clear_alert_state.json"
BACKUP_CLEAR_ALERT_HEARTBEAT_HOURS = 24   # この時間経過で同条件でも再告知 (墓場化防止)
BACKUP_CLEAR_ALERT_GROWTH = 20            # 候補がこの件数以上 増えたら悪化とみなし再告知


def _is_benign_url_swap(mismatch: dict) -> bool:
    """compare-and-clear mismatch が「HQ が別の生きた仕入元URLに差し替えた」だけか。

    ★ 2026-08-13: この形は設計どおりの競合 (監視が売切と確認 → 消す直前に HQ が新URLを入れた)。
      消さなかったのが正解で、次 cycle が新URLを普通に見る = **人が何もすることがない**。
      対処不能な通知を鳴らすと、本当に見るべき通知まで無視されるようになる。
      セル値が URL でない (空・壊れた値) 場合だけ要対応として扱う。
    """
    actual = (mismatch.get("actual") or "").strip()
    expected = (mismatch.get("expected_url") or "").strip()
    return bool(actual) and actual != expected and actual.startswith(("http://", "https://"))


def _should_emit_backup_clear_alert(held_max: int, mismatch_n: int) -> bool:
    """desktop file+mail を出すべきか (throttle 判定)。ログ出力自体は常に行う想定。

    - mismatch (compare-and-clear 不一致) は actionable → 常に告知。
    - HOLD のみ (既知 backlog) は 新規/+GROWTH悪化/HEARTBEAT経過 のいずれかで告知。
    - 判定に失敗したら保守的に True (silent 化しない方を優先)。
    """
    if mismatch_n > 0:
        return True
    if held_max <= 0:
        return False
    try:
        import json as _json  # noqa: PLC0415
        prev = {}
        if BACKUP_CLEAR_ALERT_STATE.exists():
            prev = _json.loads(BACKUP_CLEAR_ALERT_STATE.read_text(encoding="utf-8"))
        now = datetime.now()
        emit = True
        last_ts = prev.get("ts")
        last_max = int(prev.get("held_max", 0))
        if last_ts:
            try:
                elapsed_h = (now - datetime.fromisoformat(last_ts)).total_seconds() / 3600.0
            except Exception:
                elapsed_h = 1e9
            # 既知条件 (件数が増えていない かつ HEARTBEAT 未満) なら告知しない
            if held_max <= last_max + BACKUP_CLEAR_ALERT_GROWTH and elapsed_h < BACKUP_CLEAR_ALERT_HEARTBEAT_HOURS:
                emit = False
        if emit:
            BACKUP_CLEAR_ALERT_STATE.write_text(
                _json.dumps({"ts": now.isoformat(timespec="seconds"), "held_max": held_max},
                            ensure_ascii=False), encoding="utf-8")
        return emit
    except Exception:
        return True   # 判定失敗 → 保守的に告知 (silent 化しない)
# 検体テスト自体は数秒だが、他 cycle / chrome / Defender と重なると実測 40s まで伸びる
# (2026-08-13 01:30 は 120s を超えて timeout → 巡回 abort = 在庫監視 4h 空白)。
# 余裕を持たせた上で、timeout は「検出ロジックが壊れた」証拠ではないので retry する。
PYTEST_PRECHECK_TIMEOUT_SEC = 300
PYTEST_PRECHECK_ATTEMPTS = 3       # timeout/実行不能 のみ retry (テスト failed は即 abort)
PYTEST_PRECHECK_RETRY_WAIT_SEC = 30

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
def _lock_pid_alive(content: str) -> Optional[bool]:
    """lock 内容の pid/host からプロセス生存を判定。True=生存 / False=死亡 / None=判定不能。

    ★ 2026-07-26: PC 再起動/クラッシュで cycle が kill されると lock が残り、時間ベース(6h)の
      staleness まで次の巡回がブロックされる (実害: 2026-07-26 08:03 再起動で ~4.5h 監視の穴)。
      pid が同一 host で存在しなければ即 stale と判定して復帰する。
    """
    m_pid = re.search(r"pid=(\d+)", content or "")
    m_host = re.search(r"host=(\S+)", content or "")
    if not m_pid:
        return None
    # 別 host の lock は当機で pid 判定不能 (単機運用だが安全側)
    if m_host and m_host.group(1) != socket.gethostname():
        return None
    pid = int(m_pid.group(1))
    # ★ Windows では os.kill(pid,0) は TerminateProcess を呼び「プロセスを終了」してしまう危険がある
    #   (生存チェックにならない)。tasklist で該当 pid の存在を安全に確認する (ctypes handle の落とし穴回避)。
    if sys.platform == "win32":
        try:
            import subprocess  # noqa: PLC0415
            out = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True, text=True, timeout=10,
            )
            # 一致すれば pid を含む行が出る。無一致は "実行されていません/No tasks" のみ (pid を含まない)。
            return str(pid) in (out.stdout or "")
        except Exception:
            return None
    # POSIX: signal 0 は安全な存在確認 (終了させない)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True    # 存在するが権限なし = 生存
    except Exception:
        return None


def _acquire_lock(test_mode: bool = False, wait_minutes: int = 0) -> bool:
    """Returns True if lock acquired. False if already held (and not stale).

    wait_minutes > 0 なら、保持中でも解放を待ってから再試行する (2026-07-27)。
    前 cycle が数分〜1h 長引いただけで自分の巡回が丸ごと落ちる (= 監視の穴) のを自己回復させる。
    """
    deadline = time.time() + wait_minutes * 60
    while True:
        if _try_acquire_lock(test_mode):
            return True
        if time.time() >= deadline:
            return False
        _log(f"[!] lock 解放待ち... (残り {max(0, deadline - time.time())/60:.0f} min)", test_mode)
        time.sleep(LOCK_WAIT_POLL_SEC)


def _try_acquire_lock(test_mode: bool = False) -> bool:
    """1 回だけ lock 取得を試みる (待たない)。"""
    if LOCK_FILE.exists():
        try:
            age = time.time() - LOCK_FILE.stat().st_mtime
            content = LOCK_FILE.read_text(encoding="utf-8", errors="replace")[:200]
            # ★ PID 生存チェック優先: プロセスが死んでいれば age に依らず stale (再起動/クラッシュ即復帰)
            alive = _lock_pid_alive(content)
            if alive is False:
                _log(f"[!] stale lock 検出 (pid 死亡 = 再起動/クラッシュ)、削除して続行 (content: {content})", test_mode)
                LOCK_FILE.unlink(missing_ok=True)
            elif age < LOCK_STALE_HOURS * 3600:
                # 生存 or 判定不能 かつ 6h 未満 → 保持中とみなす (誤って二重起動しない安全側)
                _log(f"[!] lock 保持中 (pid_alive={alive}, age {age/60:.1f} min < {LOCK_STALE_HOURS}h, content: {content})", test_mode)
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
# 巡回停止 (staleness) の非-silent 検知
# ============================================================================
def _emit_nonsilent_alert(tag: str, subject: str, msg: str, test_mode: bool = False):
    """desktop ALERT file + gmail + toast の 3ch 告知 (pythonw でも気づける)。fail 時も他 ch は継続。"""
    _notify_toast(subject[:60], msg[:200])
    try:
        desk = (Path.home() / "OneDrive" / "デスクトップ"
                / f"ALERT_iMakInventory_{tag}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
        desk.write_text(msg, encoding="utf-8")
        _log(f"  [★{tag}] desktop ALERT 出力: {desk.name}", test_mode)
    except Exception as e:
        _log(f"  [!] {tag} desktop alert 失敗: {type(e).__name__}: {e}", test_mode)
    try:
        from email_notifier import _send_via_gmail  # noqa: PLC0415
        from auth.encrypted_gmail import load_gmail_config  # noqa: PLC0415
        _cfg = load_gmail_config()
        if _cfg:
            _a, _p, _t = _cfg
            _send_via_gmail(_a, _p, _t, subject, msg)
            _log(f"  [★{tag}] alert mail 送信", test_mode)
    except Exception as e:
        _log(f"  [!] {tag} mail 失敗: {type(e).__name__}: {e}", test_mode)


def _cycle_label_of(d: dict) -> str:
    """cycle_log から実体の label を判定する。

    ★ `sheet_label` は CLI 既定値のまま "SHEET" 固定で記録される (LOW 巡回でも "SHEET")。
      2026-07-27 の実データで確認 (sheet='low' / sheet_label='SHEET')。判定に使うと LOW が
      永久に「履歴なし」となり staleness が発火しない = silent に逆戻りするため、
      **実際に指定された `sheet` を正**とする。monitor.by_sheet があれば補助的に使う。
    """
    sheet = str(d.get("sheet") or "").lower()
    if sheet == "low":
        return "LOW"
    if sheet in ("high", "both"):
        return "SHEET"
    by_sheet = list(((d.get("phases") or {}).get("monitor") or {}).get("by_sheet") or {})
    return by_sheet[0] if by_sheet else str(d.get("sheet_label") or "SHEET")


def _check_ebay_api_usage(test_mode: bool = False) -> dict:
    """eBay Trading API の日次消費量を見て、上限手前で 1 日 1 回だけ非-silent 告知。

    上限に当たると取下げ upload が全滅する (2026-07-04 の 24 件漏れ) ため、当たる前に知らせる。
    計測が読めない場合は 0 件扱い (告知しない = 誤報より無音を選ぶ。実害検知は既存の 518 分類が担う)。
    """
    try:
        from ebay_actions.trading_api_client import read_api_usage  # noqa: PLC0415
        usage = read_api_usage()
    except Exception as e:
        _log(f"  [!] API usage 読取失敗: {type(e).__name__}: {e}", test_mode)
        return {}
    total = int(usage.get("total") or 0)
    threshold = int(EBAY_API_DAILY_LIMIT * EBAY_API_WARN_RATIO)
    usage["threshold"] = threshold
    usage["limit"] = EBAY_API_DAILY_LIMIT
    if total < threshold:
        return usage
    _log(f"  [★eBay API] 本日の呼出 {total} 件 (閾値 {threshold} / 上限 {EBAY_API_DAILY_LIMIT})", test_mode)
    try:    # 同日 1 回だけ告知
        prev = json.loads(EBAY_API_ALERT_STATE.read_text(encoding="utf-8")) \
            if EBAY_API_ALERT_STATE.exists() else {}
        if prev.get("date") == usage.get("date"):
            usage["alerted"] = False
            return usage
        EBAY_API_ALERT_STATE.write_text(json.dumps({"date": usage.get("date"), "total": total}),
                                        encoding="utf-8")
    except Exception:
        pass    # state 不明なら告知側に倒す
    top = sorted((usage.get("by_call") or {}).items(), key=lambda kv: -kv[1])[:5]
    msg = (f"本日の eBay Trading API 呼出が {total} 件 (上限 {EBAY_API_DAILY_LIMIT} の "
           f"{total / EBAY_API_DAILY_LIMIT:.0%}) に達しました。\n"
           "上限に当たると取下げ upload が全滅し、売切品が eBay に残ります "
           "(2026-07-04 に同型で取下げ漏れ 24 件)。\n"
           "対処: 不要な再実行 (手動 audit / 再 upload) を控える。翌日 0 時 (PST) にリセットされます。\n\n"
           "内訳 (上位):\n" + "\n".join(f"  - {k}: {v}" for k, v in top))
    _emit_nonsilent_alert("ebay_api_usage",
                          "[★iMakInventory] eBay API 日次上限に接近 (取下げ不能リスク)", msg, test_mode)
    usage["alerted"] = True
    return usage


def _last_cycle_success(label: str) -> Optional[datetime]:
    """cycle_*.jsonl から label の最終「完走」時刻を返す (無ければ None)。"""
    # file 名が cycle_<YYYYmmdd_HHMMSS>.jsonl = 名前降順が時刻降順 (mtime は同秒で不定順になる)
    files = sorted(DECISION_LOG_DIR.glob("cycle_*.jsonl"), key=lambda p: p.name, reverse=True)[:300]
    for p in files:   # 最初に見つかった完走が最新
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if _cycle_label_of(d) != label or not str(d.get("status", "")).startswith("success"):
            continue
        try:
            return datetime.fromisoformat(d.get("ts_end") or d.get("ts_start"))
        except Exception:
            continue
    return None


def _check_cycle_staleness(test_mode: bool = False) -> list:
    """全 label の「最後の完走からの経過」を突合し、想定間隔超過を非-silent 告知。

    skip 時だけでなく毎 cycle 末に呼ぶ (= 自分以外の label が止まっていても気づける)。
    完走記録が 1 件も無い label は判定不能として alert しない (初回導入時の誤報防止)。
    """
    stale = []
    now = datetime.now()
    for label, interval_h in CYCLE_INTERVAL_HOURS.items():
        last = _last_cycle_success(label)
        if last is None:
            continue
        elapsed_h = (now - last).total_seconds() / 3600.0
        limit_h = interval_h * CYCLE_STALE_MULT
        if elapsed_h > limit_h:
            stale.append({"label": label, "elapsed_h": round(elapsed_h, 1),
                          "limit_h": round(limit_h, 1), "last_success": last.isoformat(timespec="seconds")})
    if not stale:
        return []

    # throttle (同 label を 6h 以内に再告知しない)。判定失敗時は告知側に倒す (silent 化しない)。
    to_emit = stale
    try:
        prev = {}
        if CYCLE_STALE_ALERT_STATE.exists():
            prev = json.loads(CYCLE_STALE_ALERT_STATE.read_text(encoding="utf-8"))
        to_emit = []
        for s in stale:
            last_ts = prev.get(s["label"])
            if last_ts:
                try:
                    if (now - datetime.fromisoformat(last_ts)).total_seconds() / 3600.0 \
                            < CYCLE_STALE_ALERT_THROTTLE_HOURS:
                        continue
                except Exception:
                    pass
            to_emit.append(s)
        if to_emit:
            prev.update({s["label"]: now.isoformat(timespec="seconds") for s in to_emit})
            CYCLE_STALE_ALERT_STATE.write_text(
                json.dumps(prev, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        _log(f"  [!] staleness throttle 判定失敗 (告知側に倒す): {type(e).__name__}: {e}", test_mode)

    # ログには常に出す (= 非 silent 維持)、desktop/mail は throttle 後のみ
    for s in stale:
        _log(f"  [★巡回停止] {s['label']}: 最終完走 {s['last_success']} から {s['elapsed_h']}h "
             f"(想定 {s['limit_h']}h 以内) = 監視が止まっています", test_mode)
    if to_emit:
        lines = [f"  - {s['label']}: 最終完走 {s['last_success']} から {s['elapsed_h']}h 経過 "
                 f"(想定 {s['limit_h']}h 以内)" for s in to_emit]
        msg = ("巡回が想定間隔を超えて実行されていません (在庫切れを検知できない = 取下げ漏れリスク)。\n"
               "よくある原因: 前 cycle の長期化による lock 競合 / Task Scheduler 停止 / PC 停止。\n"
               "対処: Task Scheduler の起動時刻が他 cycle と重なっていないか、"
               "手動で `python run_cycle.py --sheet <high|low>` が通るかを確認してください。\n\n"
               + "\n".join(lines))
        _emit_nonsilent_alert("cycle_stale", "[★iMakInventory] 巡回が停止しています (取下げ漏れリスク)",
                              msg, test_mode)
    return stale


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
    """巡回開始前に offline 検体テストを実行。失敗時は巡回中止 (fail-closed).

    Returns: {"status": "passed" | "failed" | "error", "stdout_tail", "stderr_tail", "elapsed"}
    DOM 仕様変更で検出ロジックが壊れていないか cycle 前に物理担保する。

    ★ 2026-08-13: timeout / 実行不能 (status=error) は **検出ロジックが壊れた証拠ではない**
      (他 cycle と重なった時のマシン負荷等)。それで巡回ごと落とすと在庫監視が空白になり、
      fail-OPEN 側に転ぶ。よって error のみ PYTEST_PRECHECK_ATTEMPTS 回まで retry する。
      テストが実際に落ちた (failed) は DOM 仕様変更の疑い → retry せず即 abort (fail-closed 維持)。
    """
    _log("=== Phase 0/4: pytest precheck (offline 検体) ===", test_mode)
    last_err = None
    for attempt in range(1, PYTEST_PRECHECK_ATTEMPTS + 1):
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
                _log(f"  [OK] pytest precheck pass ({elapsed:.1f}s, attempt {attempt})", test_mode)
                return {
                    "status": "passed",
                    "elapsed_sec": round(elapsed, 2),
                    "attempts": attempt,
                    "stdout_tail": (result.stdout or "")[-500:],
                }
            # テストが落ちた = 検出ロジック側の疑い → retry せず abort
            _log(f"  [NG] pytest precheck FAILED rc={result.returncode} ({elapsed:.1f}s)", test_mode)
            return {
                "status": "failed",
                "returncode": result.returncode,
                "elapsed_sec": round(elapsed, 2),
                "attempts": attempt,
                "stdout_tail": (result.stdout or "")[-1500:],
                "stderr_tail": (result.stderr or "")[-500:],
            }
        except subprocess.TimeoutExpired:
            last_err = f"timeout {PYTEST_PRECHECK_TIMEOUT_SEC}s"
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
        _log(f"  [!] pytest precheck 実行不能 ({last_err}) attempt {attempt}"
             f"/{PYTEST_PRECHECK_ATTEMPTS}", test_mode)
        if attempt < PYTEST_PRECHECK_ATTEMPTS:
            time.sleep(PYTEST_PRECHECK_RETRY_WAIT_SEC)
    return {"status": "error", "error": last_err, "attempts": PYTEST_PRECHECK_ATTEMPTS}


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
             "url_alerts_count": 0, "by_sheet": {}, "error_rows": [],
             "persistent_err_rows": [], "dead_source_rows": [], "price_surge": [],
             "backup_clear_cleared": 0, "backup_clear_held": [], "backup_clear_mismatch": [],
             "rescue_new": 0, "rescue_current": 0}

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
            # 持続エラー (連続3回以上) も sheet 跨ぎ集約 → メール別掲用
            for pr in (stats.get("persistent_err_rows") or []):
                grand["persistent_err_rows"].append({**pr, "sheet": label})
            for dr in (stats.get("dead_source_rows") or []):
                grand["dead_source_rows"].append({**dr, "sheet": label})
            # 価格急増ガード発火 (supplier 単位) を sheet 跨ぎ集約 → cycle 後に ALERT 別掲
            for sup in (stats.get("price_surge_held") or []):
                st = (stats.get("price_surge_stats") or {}).get(sup, {})
                grand["price_surge"].append({"sheet": label, "supplier": sup, **st})
            # 補URL救済 (フック2、Phase1 救済率 signal) を集約 (正常イベント = alert なし、ログのみ)
            rc = stats.get("rescue") or {}
            grand["rescue_new"] += rc.get("new_events", 0)
            grand["rescue_current"] += rc.get("current_rescued", 0)
            # 補URL消込の HOLD (急増ガード) / mismatch (HQ差替等) を集約 → ALERT 別掲
            bc = stats.get("backup_clear") or {}
            grand["backup_clear_cleared"] += bc.get("cleared", 0)
            if bc.get("held") or bc.get("surge"):
                grand["backup_clear_held"].append(
                    {"sheet": label, "candidate_count": bc.get("candidate_count", 0),
                     "new_count": bc.get("new_count", bc.get("candidate_count", 0))})
            for mm in (bc.get("skipped_mismatch") or []):
                grand["backup_clear_mismatch"].append({**mm, "sheet": label})
        except Exception as e:
            _log(f"  [NG] [{label}] 例外: {type(e).__name__}: {e}", test_mode)
            grand["by_sheet"][label] = {"error": f"{type(e).__name__}: {e}"}

    # ★ 価格急増ガード ALERT: scraper 系統崩壊で M/K が HOLD された = 要 DOM 確認。
    #   pythonw (Task Scheduler) 下でも気づけるよう desktop ALERT file + mail で必ず告知 (非 silent)。
    #   D/O (取下げ) は正常書込のため fail-OPEN ではないが、価格 stale 放置は出品機会損失につながる。
    if grand["price_surge"]:
        _lines = [f"  - [{s['sheet']}] {s['supplier']}: 急変 {s.get('surged','?')}/{s.get('total','?')} 行 "
                  f"(ratio={s.get('ratio','?')})" for s in grand["price_surge"]]
        _msg = ("価格急増ガードが発火し、以下 supplier の M(現在価格)/K(ポイント) 書込を HOLD しました。\n"
                "scraper の DOM 構造変化で系統的に誤価格を拾っている疑いがあります。\n"
                "DOM 検体を採取し marker/regex を確認してください (fail-closed のため誤汚染ではなく "
                "価格 stale 側 = 安全)。D/O (取下げ) は正常書込のため取下げ漏れはありません。\n\n"
                + "\n".join(_lines))
        _log(f"  [★価格急増ガード] {len(grand['price_surge'])} supplier HOLD → ALERT 発報", test_mode)
        _notify_toast("iMakInventory 価格急増ガード発火", _msg[:200])
        try:
            desk = (Path.home() / "OneDrive" / "デスクトップ"
                    / f"ALERT_iMakInventory_price_surge_"
                      f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
            desk.write_text(_msg, encoding="utf-8")
            _log(f"  [★価格急増ガード] desktop ALERT 出力: {desk.name}", test_mode)
        except Exception as e:
            _log(f"  [!] 価格急増ガード desktop alert 失敗: {type(e).__name__}: {e}", test_mode)
        try:
            from email_notifier import _send_via_gmail  # noqa: PLC0415
            from auth.encrypted_gmail import load_gmail_config  # noqa: PLC0415
            _cfg = load_gmail_config()
            if _cfg:
                _a, _p, _t = _cfg
                _send_via_gmail(_a, _p, _t,
                                "[★iMakInventory] 価格急増ガード発火 (scraper系統崩壊疑い / 価格書込HOLD)",
                                _msg)
                _log("  [★価格急増ガード] alert mail 送信", test_mode)
        except Exception as e:
            _log(f"  [!] 価格急増ガード mail 失敗: {type(e).__name__}: {e}", test_mode)

    # ★ 補URL消込 ALERT: 消込急増ガード HOLD / compare-and-clear mismatch (HQ差替等) を非 silent 告知。
    #   いずれも D/O(取下げ) は正常書込 = fail-OPEN ではない (延命枠の衛生管理レイヤ)。silent drop 禁止。
    if grand["backup_clear_held"] or grand["backup_clear_mismatch"]:
        _held = grand["backup_clear_held"]
        _mm_all = grand["backup_clear_mismatch"]
        # ★ 2026-08-13: mismatch のうち「セルが別の生きた仕入元URLに差し替わっている」ものは
        #   HQ が補充した = 設計どおりの競合であり、**人が何もすることがない** (次 cycle が
        #   新URLを普通に見る)。これで desktop ALERT を鳴らすと「対処不能な通知」になる。
        #   数える・ログに出すのは続けるが、告知対象からは外す。
        #   URL でないもの (空/壊れた値) は従来どおり要対応として告知する。
        _mm = [m for m in _mm_all if not _is_benign_url_swap(m)]
        _mm_swap = [m for m in _mm_all if _is_benign_url_swap(m)]
        if _mm_swap:
            _log(f"  [補URL消込] HQ差替による mismatch {len(_mm_swap)} 件 "
                 f"(= 正常な競合、告知しない): "
                 + ", ".join(f"row{m.get('row_index')}slot{m.get('slot')}" for m in _mm_swap[:10]),
                 test_mode)
        _parts = []
        if _held:
            _parts.append(
                "【消込急増ガード HOLD】" + ", ".join(
                    f"[{h['sheet']}] 新規{h.get('new_count', '?')}件 (候補{h['candidate_count']}件)"
                    for h in _held)
                + " → 一括消込を保留 (誤一括削除を防止)。\n"
                "  ★ 判定基準は **今 cycle 新規** (積み残しは cycle 毎に自動ドレインされるので "
                "backlog では発火しない)。新規が一気に湧く = **scraper 系統崩壊の疑い** → "
                "まず候補一覧の supplier 偏りと DOM 検体を確認。genuine と確認できたら:\n"
                "    1) 確認: python -m tools.supervised_backup_drain\n"
                "    2) 実削除: python -m tools.supervised_backup_drain --reverify-snkrdunk --execute\n"
                "  (compare-and-clear + 復元アーカイブで安全。触るのは補URL(AC-AG)のみ)。\n"
                "  ※ 万一 別supplier scraper の一斉偽sold崩壊の可能性が疑わしい時のみ、"
                "先に候補一覧の supplier 偏りを確認すること。")
        if _mm:
            _parts.append(f"【compare-and-clear mismatch {len(_mm)}件】セル値≠確認URL "
                          "(HQ が生きた新URLに差替 or 変化) → 消さずに要対応記録。")
            for m in _mm[:15]:
                _parts.append(f"  - [{m.get('sheet')}] row{m.get('row_index')} "
                              f"slot{m.get('slot')}: expected={ (m.get('expected_url') or '')[:40]}")
        if not _parts:
            # 告知対象が「HQ差替だけ」= 対処不能な通知しか残らない → 発報しない (ログには出済)
            _log("  [補URL消込] 告知対象なし (HQ差替のみ) → ALERT 発報しない", test_mode)
            _parts = None
        _msg = ("補URL 売切消込で要対応が発生しました (D/O 取下げは正常 = fail-OPEN ではない)。\n\n"
                + "\n".join(_parts)) if _parts else ""
        # ★ throttle: 既知 backlog の HOLD を毎 cycle 4h毎に desktop file+mail 量産するとアラート疲労。
        #   cycle ログには常に出す (非 silent 維持) が、desktop file+mail は「新規/悪化/24h経過/mismatch有」時のみ。
        _held_max = max((h.get("candidate_count", 0) for h in _held), default=0)
        _emit = bool(_msg) and _should_emit_backup_clear_alert(_held_max, len(_mm))
        if _emit:
            _log(f"  [★補URL消込] HOLD={len(_held)} / mismatch={len(_mm)} → ALERT 発報", test_mode)
            _notify_toast("iMakInventory 補URL消込 要対応", _msg[:200])
            try:
                desk = (Path.home() / "OneDrive" / "デスクトップ"
                        / f"ALERT_iMakInventory_backup_clear_"
                          f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
                desk.write_text(_msg, encoding="utf-8")
                _log(f"  [★補URL消込] desktop ALERT 出力: {desk.name}", test_mode)
            except Exception as e:
                _log(f"  [!] 補URL消込 desktop alert 失敗: {type(e).__name__}: {e}", test_mode)
            try:
                from email_notifier import _send_via_gmail  # noqa: PLC0415
                from auth.encrypted_gmail import load_gmail_config  # noqa: PLC0415
                _cfg = load_gmail_config()
                if _cfg:
                    _a, _p, _t = _cfg
                    _send_via_gmail(_a, _p, _t,
                                    "[★iMakInventory] 補URL消込 要対応 (急増HOLD/mismatch)", _msg)
                    _log("  [★補URL消込] alert mail 送信", test_mode)
            except Exception as e:
                _log(f"  [!] 補URL消込 mail 失敗: {type(e).__name__}: {e}", test_mode)
        else:
            # 非 silent: 告知は throttle したが cycle ログ + report には必ず残す (墓場化しない)。
            _log(f"  [補URL消込] HOLD={len(_held)}(候補最大{_held_max}) / mismatch=0 "
                 f"= 既知 backlog 継続 (desktop/mail は throttle、次は悪化 or 24h で再告知)", test_mode)

    # 補URL救済 (Phase1 救済率 signal)。正常イベント = ログのみ (HQ が 補URL救済ログ から集計)。
    if grand["rescue_new"] or grand["rescue_current"]:
        _log(f"  [補URL救済] 新規救済 {grand['rescue_new']} 件 / 現在救済中 {grand['rescue_current']} 件 "
             f"(主死→補で延命、Phase1 救済率 signal)", test_mode)
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
# 復活 (revive) phase — 2026-08-07 revive_qty1_impl §9
# ============================================================================
def _phase_revive_csv(
    sheet: str,
    test_mode: bool,
    cycle_started_at: datetime,
    single_sheet_id: Optional[str] = None,
    single_sheet_label: Optional[str] = None,
    high_sheet_id: Optional[str] = None,
    low_sheet_id: Optional[str] = None,
    max_per_cycle: Optional[int] = None,
    provided_qty_map: Optional[dict] = None,
) -> dict:
    """revive_csv_generator (mode=revive) で qty=1 化 CSV を生成 (取下げの対称)。

    cycle_started_at は 3点セット gate の O 列比較用。 phase 実行開始時刻を渡す。
    """
    _log(f"=== Phase 2.5/3.5: revive_csv_generator (sheet={sheet}) ===", test_mode)
    try:
        return run_revive_csv(
            sheet=sheet, dry_run=False,
            max_per_cycle=max_per_cycle,
            high_sheet_id=high_sheet_id, low_sheet_id=low_sheet_id,
            single_sheet_id=single_sheet_id,
            single_sheet_label=single_sheet_label,
            cycle_started_at=cycle_started_at,
            provided_qty_map=provided_qty_map,
        )
    except Exception as e:
        _log(f"  [NG] revive_csv 例外: {type(e).__name__}: {e}", test_mode)
        return {"error": f"{type(e).__name__}: {e}"}


def _phase_revive_upload(csv_path_str: str, test_mode: bool) -> dict:
    """Trading API ReviseInventoryStatus (qty=1) で復活 + _verify_qty_gt_zero verify。

    _phase_upload と同じく upload_csv_via_trading_api を通す (CSV の Quantity 列で
    qty=0/1 が分岐 → uploader 側で _verify_qty_zero / _verify_qty_gt_zero を振分)。
    """
    _log(f"=== Phase 3.5/3.5: trading_api_uploader.revive_upload (csv={csv_path_str}) ===",
         test_mode)
    try:
        result = upload_csv_via_trading_api(Path(csv_path_str), dry_run=False)
        if not result.get("success"):
            result["error"] = (
                f"Trading API revive: total={result.get('total')} "
                f"ok={result.get('ok')} ng={result.get('ng')}"
            )
        return result
    except Exception as e:
        _log(f"  [NG] Trading API revive_upload 例外: {type(e).__name__}: {e}", test_mode)
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

    # lock 保持中でも即諦めず解放を待つ (前 cycle の長期化で巡回が丸ごと落ちるのを自己回復)
    if not _acquire_lock(test_mode, wait_minutes=0 if test_mode else LOCK_WAIT_MINUTES):
        cycle_log["status"] = "skipped_lock_held"
        cycle_log["ts_end"] = datetime.now().isoformat(timespec="seconds")
        cycle_log["waited_minutes"] = 0 if test_mode else LOCK_WAIT_MINUTES
        path = _record_cycle_log(cycle_log)
        _notify_toast("iMakInventory: skipped",
                      f"lock 保持中、巡回 skip ({path.name})")
        # skip 自体を silent にしない: 「止まっている」水準なら 3ch 告知
        try:
            cycle_log["staleness"] = _check_cycle_staleness(test_mode)
        except Exception as e:
            _log(f"  [!] staleness 判定失敗: {type(e).__name__}: {e}", test_mode)
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
            # ★ 2026-06-20: 旧実装は toast のみ → pythonw (Task Scheduler) 下で誰も見ず、
            # precheck 失敗で HIGH/LOW 監視が 3 日 silent 停止した (a12b776 の検体 fail 由来)。
            # desktop ALERT file + email で必ず気づけるようにする (= silent 停止を絶対回避)。
            # 原因で文面を変える: failed=検出ロジックの疑い / error=実行不能 (負荷・環境)。
            # 一律「DOM 仕様変更」と書くと、実際は環境要因の時に scraper を疑って空振りする。
            if precheck["status"] == "failed":
                _cause = (" 検体テストが実際に落ちた → DOM 仕様変更 / scraper 修正が必要"
                          " (下の tail に失敗テスト名)。")
            else:
                _cause = (f" pytest を {precheck.get('attempts', '?')} 回試して実行できず"
                          f" ({precheck.get('error')})。検出ロジックの故障ではなく実行環境側"
                          f" (負荷/timeout/python 環境) の疑い → 次 cycle で自動復帰する見込み。"
                          f" 連続する場合のみ調査。")
            msg = (f"pytest precheck 失敗 (status={precheck['status']}) → 巡回 abort。"
                   f" 在庫監視が停止 = fail-OPEN 露出。" + _cause)
            _log(f"  [★ABORT] {msg}", test_mode)
            _notify_toast("iMakInventory 巡回中止 (precheck失敗)", msg)
            _tail = (precheck.get("stdout_tail") or precheck.get("error") or "")[-1500:]
            try:
                desk = (Path.home() / "OneDrive" / "デスクトップ"
                        / f"ALERT_iMakInventory_precheck_failed_"
                          f"{cycle_log.get('ts_start','')[:13].replace(':','').replace('T','_')}.txt")
                desk.write_text(msg + "\n\n" + _tail, encoding="utf-8")
                _log(f"  [★ABORT] desktop ALERT 出力: {desk.name}", test_mode)
            except Exception as e:
                _log(f"  [!] precheck abort desktop alert 失敗: {type(e).__name__}: {e}", test_mode)
            try:
                from email_notifier import _send_via_gmail  # noqa: PLC0415
                from auth.encrypted_gmail import load_gmail_config  # noqa: PLC0415
                _cfg = load_gmail_config()
                if _cfg:
                    _a, _p, _t = _cfg
                    _send_via_gmail(_a, _p, _t,
                                    "[★iMakInventory] 巡回中止: precheck失敗 (在庫監視停止)",
                                    msg + "\n\n" + _tail)
                    _log("  [★ABORT] precheck 失敗 alert mail 送信", test_mode)
            except Exception as e:
                _log(f"  [!] precheck abort mail 失敗: {type(e).__name__}: {e}", test_mode)
            # ★ 2026-08-13: abort も cycle log に残す。残さないと decision_log 上は
            #   「その時間の巡回が存在しない」ように見え、後から稼働率を数えた時に
            #   停止していた事実が消える (08-13 01:30 の abort が履歴に無かった)。
            cycle_log["ts_end"] = datetime.now().isoformat(timespec="seconds")
            try:
                _record_cycle_log(cycle_log)
            except Exception as e:
                _log(f"  [!] abort cycle log 記録失敗: {type(e).__name__}: {e}", test_mode)
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
                # 滞留 pending 検知 (2026-06-11): network 失敗等で複数 cycle 取下げ
                # 失敗し続ける item を即時エスカレーション (= silent 滞留 = 漏れ継続疑い)。
                try:
                    from ebay_actions.revise_csv_generator import get_stuck_pending_items  # noqa: PLC0415
                    stuck = get_stuck_pending_items()
                    cycle_log["phases"]["pending_stuck"] = stuck
                    if stuck:
                        _log(f"  [★要対応] 取下げ滞留 {len(stuck)} 件 "
                             f"(最古 {stuck[0]['age_hours']}h pending) → email 別掲",
                             test_mode)
                except Exception as e:
                    _log(f"  [!] stuck pending 検知失敗: {type(e).__name__}: {e}",
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

        # ================================================================
        # Phase 2.5/3.5: 復活 (qty=1) CSV 生成 + upload
        # 2026-08-07 revive_qty1_impl §9: pending_revive.jsonl に 2 cycle 連続
        # 確定した行があれば URL白 → 3点セット → 二重出品 → 採算 の 4 gate を掛けて
        # qty=1 化 CSV を出す。 monitor_only や burst 発火時は skip。
        # ================================================================
        if not monitor_only:
            try:
                pending_revive_exists = PENDING_REVIVE_FILE.exists() and \
                    PENDING_REVIVE_FILE.stat().st_size > 0
            except OSError:
                pending_revive_exists = False
            if pending_revive_exists:
                progress_writer.update(phase="revive_csv", force=True)
                cycle_started_dt = datetime.fromisoformat(cycle_log["ts_start"])
                rv = _phase_revive_csv(
                    sheet, test_mode,
                    cycle_started_at=cycle_started_dt,
                    single_sheet_id=sheet_id,
                    single_sheet_label=sheet_label,
                    high_sheet_id=high_sheet_id,
                    low_sheet_id=low_sheet_id,
                )
                cycle_log["phases"]["revive_csv"] = rv
                revive_csv_path = rv.get("csv_path") if isinstance(rv, dict) else None
                if not revive_csv_path or skip_upload:
                    _log(f"  revive upload skip (csv_path={revive_csv_path}, "
                         f"skip_upload={skip_upload})", test_mode)
                    cycle_log["phases"]["revive_upload"] = {"skipped":
                        "csv_path none or skip_upload"}
                else:
                    progress_writer.update(phase="revive_upload", force=True)
                    ru = _phase_revive_upload(revive_csv_path, test_mode)
                    cycle_log["phases"]["revive_upload"] = ru
                    # drain: 成功 item を processed_revive.jsonl に archive、 pending から除去
                    try:
                        succ_ids = [res["item_id"] for res in (ru.get("results") or [])
                                     if res.get("success")]
                        moved = drain_pending_revive(succ_ids)
                        failed_kept = len(rv.get("allowed_item_ids") or []) - len(succ_ids)
                        _log(f"  pending_revive → processed_revive archive: {moved} 件 "
                             f"(失敗 {failed_kept} 件は pending 残置 → 次 cycle で retry)",
                             test_mode)
                        # ★ 2026-08-17: 復活できた = 急増ガードで HOLD した理由が消えた。
                        #   要対応キューを閉じる (閉じないと片付いた項目が残り続け件数が嘘をつく)。
                        from monitor_listings import resolve_action_required  # noqa: PLC0415
                        _closed = resolve_action_required(
                            succ_ids, "revive_burst_guard_holdout", dry_run=dry_run)
                        if _closed:
                            _log(f"  要対応 close: revive 成功で {_closed} 件を解決済に退避",
                                 test_mode)
                    except Exception as e:
                        _log(f"  [!] drain_pending_revive 失敗: {type(e).__name__}: {e}",
                             test_mode)
                    # verify 通過せず (silent drop 禁止) → action_required.jsonl 記録
                    try:
                        from monitor_listings import append_action_required  # noqa: PLC0415
                        revive_verify_failed = [
                            res for res in (ru.get("results") or [])
                            if not res.get("success") and res.get("verified") is False
                            and (res.get("quantity") or 0) > 0
                        ]
                        for res in revive_verify_failed:
                            append_action_required(
                                sheet_label=res.get("sheet_label", ""),
                                result={
                                    "row_index": res.get("row_index", -1),
                                    "url":       res.get("url", ""),
                                    "item_id":   res.get("item_id", ""),
                                    "title":     res.get("title", ""),
                                    "supplier":  res.get("supplier", ""),
                                    "raw_status": "revive_verify_failed",
                                },
                                reason="revive_verify_gt0_giveup",
                                dry_run=False,
                            )
                        if revive_verify_failed:
                            _log(f"  [★要対応] revive in-cycle verify 通過せず: "
                                 f"{len(revive_verify_failed)} 件 → action_required.jsonl",
                                 test_mode)
                    except Exception as e:
                        _log(f"  [!] revive action_required 記録失敗: "
                             f"{type(e).__name__}: {e}", test_mode)
            else:
                _log(f"  revive skip (pending_revive.jsonl 空)", test_mode)
                cycle_log["phases"]["revive_csv"] = {"skipped": "no pending_revive"}

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

    # ★ 全 label の巡回 staleness を毎 cycle 突合 (自分以外が止まっていても気づける = 非 silent)
    try:
        cycle_log["staleness"] = _check_cycle_staleness(test_mode)
    except Exception as e:
        _log(f"  [!] staleness 判定失敗: {type(e).__name__}: {e}", test_mode)

    # ★ eBay API 日次消費量 (上限に当たる前に気づく)
    try:
        cycle_log["ebay_api_usage"] = _check_ebay_api_usage(test_mode)
    except Exception as e:
        _log(f"  [!] API usage 判定失敗: {type(e).__name__}: {e}", test_mode)

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
