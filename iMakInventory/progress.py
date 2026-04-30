"""progress - run_cycle.py のライブ進捗書込 + GUI 読込 helpers.

GUI が 30 秒おきに polling して「巡回中: monitor 350/421」のように表示する
ためのファイルベース IPC。decision_log/progress_<cycle_ts>.jsonl に書込む。

【書込側 (run_cycle.py / monitor_listings.py)】
ProgressWriter インスタンスを作って update() を呼ぶ。throttle は内部で 5 秒以上
経過時のみ disk write、過剰 IO を避ける。cycle 完了時に finalize() で削除。

【読込側 (control_panel.py)】
read_latest_progress() で最新ファイルを返す (なければ None)。lock file の存在
チェックと組合せて「巡回中か / 待機中か」を判定する。
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

SCRIPT_DIR = Path(__file__).resolve().parent
DECISION_LOG_DIR = SCRIPT_DIR / "decision_log"
DECISION_LOG_DIR.mkdir(parents=True, exist_ok=True)

PROGRESS_PREFIX = "progress_"
PROGRESS_THROTTLE_SEC = 5  # 連続 update を間引く間隔


# ============================================================================
# 書込側
# ============================================================================
class ProgressWriter:
    """巡回中の進捗を JSON ファイルに throttle 書込.

    Usage:
        pw = ProgressWriter(cycle_ts="20260430_180000")
        pw.update(phase="monitor", processed=10, total=421, errors=2)
        ...
        pw.finalize()  # cycle 完了時に呼ぶ → ファイル削除
    """

    def __init__(self, cycle_ts: str):
        self.cycle_ts = cycle_ts
        self.path = DECISION_LOG_DIR / f"{PROGRESS_PREFIX}{cycle_ts}.jsonl"
        self._last_write_ts = 0.0
        self._state = {
            "cycle_ts": cycle_ts,
            "ts_start": datetime.now().isoformat(timespec="seconds"),
            "phase": "init",
            "processed": 0,
            "total": 0,
            "errors": 0,
            "ts_updated": None,
        }
        # 起動時に initial write (空の状態でも GUI が "巡回中" を検出できるよう)
        self._write(force=True)

    def update(
        self,
        phase: Optional[str] = None,
        processed: Optional[int] = None,
        total: Optional[int] = None,
        errors: Optional[int] = None,
        force: bool = False,
        **extra,
    ):
        """state を更新し、throttle に応じて disk write."""
        if phase is not None:
            self._state["phase"] = phase
        if processed is not None:
            self._state["processed"] = processed
        if total is not None:
            self._state["total"] = total
        if errors is not None:
            self._state["errors"] = errors
        for k, v in extra.items():
            self._state[k] = v
        self._write(force=force)

    def _write(self, force: bool = False):
        now = time.time()
        if not force and (now - self._last_write_ts) < PROGRESS_THROTTLE_SEC:
            return
        self._state["ts_updated"] = datetime.now().isoformat(timespec="seconds")
        try:
            self.path.write_text(
                json.dumps(self._state, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            self._last_write_ts = now
        except OSError:
            pass

    def finalize(self):
        """cycle 完了時にファイル削除 (GUI が「待機中」に戻る合図)."""
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            pass


# ============================================================================
# 読込側 (GUI)
# ============================================================================
def read_latest_progress() -> Optional[dict]:
    """最新の progress_*.jsonl を返す.

    複数ある場合は cycle_ts 降順で最新。なければ None。
    """
    files = sorted(
        DECISION_LOG_DIR.glob(f"{PROGRESS_PREFIX}*.jsonl"),
        key=lambda p: p.name,
        reverse=True,
    )
    if not files:
        return None
    try:
        return json.loads(files[0].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def cleanup_stale_progress(max_age_hours: float = 6.0) -> int:
    """壊れた cycle で残った古い progress ファイルを削除 (lock と同じ stale 判定)."""
    cutoff = time.time() - max_age_hours * 3600
    deleted = 0
    for p in DECISION_LOG_DIR.glob(f"{PROGRESS_PREFIX}*.jsonl"):
        try:
            if p.stat().st_mtime < cutoff:
                p.unlink(missing_ok=True)
                deleted += 1
        except OSError:
            pass
    return deleted
