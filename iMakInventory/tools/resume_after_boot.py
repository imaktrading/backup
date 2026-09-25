"""PC が落ちて立ち上がった時に、止まった巡回を次の予約を待たずに続きから走らせる.

2026-09-24 ADV 依頼 resume_after_crash (ユーザー判断: PC は落ちる前提で運用する)。
タスク iMakInventory_ResumeAfterBoot (ログオン時 +3分) から起動する。

1. 取下げの送り残し (DrainTakedowns) を最初に1回走らせる
2. 途中で止まった巡回を HIGH → LOW → CAND の順に1本ずつ走らせる (同時に走らせない = PC の負荷を上げない)
   「止まった」= 途中経過の記録 (checkpoint) が残っている、または lock の持ち主が死んでいて
   その後に巡回の終了記録が無い。続きからの再開そのものは巡回側 (monitor_listings) が行う。
3. 何もすることが無ければ何もしない (普通のログオンでも起動するため)
4. `--periodic` (タスク iMakInventory_ResumeCrashed、5分おき): PC は落ちずに巡回のプロセスだけが
   落ちた時 (9/24〜25 にメモリ破損で4回) に、次の予約 (最大6時間後) を待たずに続きから走らせる。
   同じ止まり方を3回走らせ直しても落ちるなら、自動ではやめてデスクトップに ALERT を置く

起動は既存の予約タスクを /run で叩く (引数・Chrome の置き場・lock を予約と完全に同じにするため)。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from proc_alive import pid_alive as _pid_alive  # noqa: E402

# pythonw から console プログラムを呼ぶ時は必ず窓を出さない (出すと作業中の画面の前面を奪う)
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
DECISION_LOG_DIR = ROOT / "decision_log"
LOG_FILE = ROOT / "logs" / "resume_after_boot.log"

# (巡回ラベル, lock ファイル, 予約タスク名) — 優先順
CYCLES = [
    ("SHEET", ".cycle.lock", "iMakInventory_Cycle"),
    ("LOW", ".cycle_LOW.lock", "iMakInventory_Cycle_LOW"),
    ("CAND", ".cycle_CAND.lock", "iMakInventory_Cycle_CAND"),
]
DRAIN_TASK = "iMakInventory_DrainTakedowns_Hourly"
CHECKPOINT_MAX_AGE_HOURS = 8        # monitor_listings.CHECKPOINT_MAX_AGE_HOURS と同じ
WAIT_START_SEC = 15 * 60            # /run 後、巡回が lock を取るまで待つ上限
WAIT_FINISH_SEC = 5 * 3600          # 1本の巡回が終わるまで待つ上限 (HIGH の最長実測 3.3h)
POLL_SEC = 60


def log(msg: str) -> None:
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line, flush=True)
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def pid_alive(pid: int) -> bool:
    """tasklist を使わない (2026-09-24: 1分おきに窓が開いて前面を奪っていた)。判定不能は生きている扱い."""
    alive = _pid_alive(pid)
    return True if alive is None else alive


def last_boot_time() -> datetime | None:
    try:
        import ctypes  # noqa: PLC0415
        from datetime import timedelta  # noqa: PLC0415
        tick = ctypes.windll.kernel32.GetTickCount64
        tick.restype = ctypes.c_ulonglong
        return datetime.now() - timedelta(milliseconds=tick())
    except Exception:
        return None


def lock_owner_alive(pid, ts) -> bool:
    """再起動前に取った lock は死んでいる (Windows は再起動後に pid を使い回す)."""
    boot = last_boot_time()
    if ts is not None and boot is not None and ts < boot:
        return False
    return pid is not None and pid_alive(pid)


def read_lock(path: Path):
    """(pid, 取得時刻) / 読めなければ (None, None)."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None, None
    m_pid = re.search(r"pid=(\d+)", text)
    m_ts = re.search(r"ts=(\S+)", text)
    try:
        ts = datetime.fromisoformat(m_ts.group(1)) if m_ts else None
    except ValueError:
        ts = None
    return (int(m_pid.group(1)) if m_pid else None), ts


def checkpoint_fresh(label: str) -> bool:
    p = DECISION_LOG_DIR / f"checkpoint_{label}.jsonl"
    if not p.exists():
        return False
    age = time.time() - p.stat().st_mtime
    return age <= CHECKPOINT_MAX_AGE_HOURS * 3600


def _cycle_label(summary: dict) -> str:
    """巡回の終了記録 → SHEET / LOW / CAND (cycle_*.jsonl は3種類が同じ場所に出る)."""
    if str(summary.get("sheet") or "").lower() == "low":
        return "LOW"
    return "CAND" if str(summary.get("sheet_label") or "").upper() == "CAND" else "SHEET"


def finished_after(label: str, ts: datetime) -> bool:
    """ts 以降に、その巡回の終了記録 (cycle_*.jsonl) があるか."""
    for p in DECISION_LOG_DIR.glob("cycle_*.jsonl"):
        m = re.match(r"cycle_(\d{8}_\d{6})", p.name)
        if not m or datetime.strptime(m.group(1), "%Y%m%d_%H%M%S") < ts:
            continue
        try:
            if _cycle_label(json.loads(p.read_text(encoding="utf-8"))) == label:
                return True
        except (OSError, ValueError, AttributeError):
            continue   # 読めない記録は「終わった証拠」にしない
    return False


def interrupted(label: str, lock_name: str) -> str | None:
    """止まった巡回なら理由、そうでなければ None."""
    lock = DECISION_LOG_DIR / lock_name
    pid, ts = read_lock(lock) if lock.exists() else (None, None)
    if lock_owner_alive(pid, ts):
        return None                                   # 今まさに走っている
    if checkpoint_fresh(label):
        return "途中経過の記録あり"
    if lock.exists():
        if ts is None:
            return "lock が読めない (最初から回す側に倒す)"
        if (datetime.now() - ts).total_seconds() <= CHECKPOINT_MAX_AGE_HOURS * 3600 \
                and not finished_after(label, ts):
            return f"lock の持ち主 (pid={pid}) が死んでいて終了記録なし"
    return None


def run_task(name: str) -> bool:
    r = subprocess.run(["schtasks", "/run", "/tn", name], capture_output=True,
                       text=True, encoding="cp932", errors="replace", creationflags=_NO_WINDOW)
    log(f"  schtasks /run {name} → exit={r.returncode} {(r.stdout or r.stderr).strip()[:120]}")
    return r.returncode == 0


def wait_cycle(lock_name: str, since: datetime) -> None:
    """その巡回が lock を取って、手放すまで待つ."""
    lock = DECISION_LOG_DIR / lock_name
    t0 = time.time()
    while time.time() - t0 < WAIT_START_SEC:
        pid, ts = read_lock(lock) if lock.exists() else (None, None)
        if pid and ts and ts >= since and lock_owner_alive(pid, ts):
            break
        time.sleep(10)
    else:
        log("  [!] 巡回が始まったのを確認できないまま 15分経過 → 次へ進む")
        return
    while time.time() - t0 < WAIT_FINISH_SEC:
        pid, ts = read_lock(lock) if lock.exists() else (None, None)
        if not lock_owner_alive(pid, ts):
            log("  巡回の終了を確認")
            return
        time.sleep(POLL_SEC)
    log("  [!] 5時間待っても終わらない → 待つのをやめて次へ進む")


def wait_others_idle() -> None:
    """他の巡回が走っている間は始めない (同時に Chrome を増やさない = PC の負荷を上げない)."""
    t0 = time.time()
    while time.time() - t0 < WAIT_FINISH_SEC:
        busy = [lk for _, lk, _ in CYCLES
                if (DECISION_LOG_DIR / lk).exists() and lock_owner_alive(*read_lock(DECISION_LOG_DIR / lk))]
        if not busy:
            return
        if time.time() - t0 < 1:
            log(f"  他の巡回が走行中 ({', '.join(busy)}) → 終わるまで待つ")
        time.sleep(POLL_SEC)
    log("  [!] 5時間待っても他の巡回が終わらない → そのまま始める")


RETRY_STATE = DECISION_LOG_DIR / "resume_retry_state.json"
MAX_RETRY = 3        # 同じ止まり方 (同じ途中経過) を続けて走らせ直す上限 — 毎回落ちるなら人が見る


def _interrupt_key(label: str, lock_name: str) -> str:
    """止まった1回を識別する: 途中経過の開始時刻 (無ければ lock の時刻)."""
    p = DECISION_LOG_DIR / f"checkpoint_{label}.jsonl"
    try:
        with open(p, encoding="utf-8") as f:
            started = json.loads(f.readline()).get("started")
        if started:
            return f"ckpt:{started}"
    except (OSError, ValueError, AttributeError):
        pass
    _, ts = read_lock(DECISION_LOG_DIR / lock_name)
    return f"lock:{ts.isoformat() if ts else '?'}"


def _load_retry() -> dict:
    try:
        d = json.loads(RETRY_STATE.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _alert_gave_up(label: str, key: str, tries: int) -> None:
    """3回走らせ直しても落ちる = 自動では直らない。人が見るための告知 (1回だけ)."""
    try:
        desk = Path.home() / "OneDrive" / "デスクトップ"
        (desk / f"ALERT_iMakInventory_cycle_keeps_crashing_{label}_{datetime.now():%Y-%m-%d_%H}.txt").write_text(
            f"{label} の巡回が {tries} 回 続けて途中で落ちたので、自動の再開をやめました ({key})。\n"
            f"次の予約の巡回までこの巡回は止まったままです。\n"
            f"見る所: iMakInventory/logs/cycle_crash.log と logs/resume_after_boot.log\n", encoding="utf-8")
    except OSError:
        pass


def main(periodic: bool = False) -> int:
    """periodic=False: ログオン時 (PC が落ちた後)。periodic=True: 5分おき (巡回のプロセスだけが落ちた時)."""
    todo = [(lab, lk, task, why) for lab, lk, task in CYCLES if (why := interrupted(lab, lk))]
    if periodic and not todo:
        return 0         # 5分おきの見回りで何も無ければ、ログも残さない
    log("=== 巡回が落ちていないかの見回り ===" if periodic else "=== 起動後の再開チェック ===")
    log("取下げの送り残しを先に1回回す")
    run_task(DRAIN_TASK)

    if not todo:
        log("止まった巡回なし → 終了")
        return 0
    retry = _load_retry()
    for lab, lk, task, why in todo:
        if periodic:
            key = _interrupt_key(lab, lk)
            ent = retry.get(lab) if isinstance(retry.get(lab), dict) else {}
            tries = ent.get("tries", 0) if ent.get("key") == key else 0
            if tries >= MAX_RETRY:
                if not ent.get("alerted"):
                    log(f"{lab}: {tries} 回走らせ直しても落ちた → 自動の再開をやめる (次の予約まで待つ)")
                    _alert_gave_up(lab, key, tries)
                    retry[lab] = {"key": key, "tries": tries, "alerted": True}
                    RETRY_STATE.write_text(json.dumps(retry, ensure_ascii=False), encoding="utf-8")
                continue
            retry[lab] = {"key": key, "tries": tries + 1}
            RETRY_STATE.write_text(json.dumps(retry, ensure_ascii=False), encoding="utf-8")
            log(f"{lab}: 巡回のプロセスが落ちている ({why}) → 続きから走らせる ({tries + 1}/{MAX_RETRY} 回目)")
        else:
            log(f"{lab}: 止まっている ({why}) → 続きから走らせる")
        wait_others_idle()
        if not interrupted(lab, lk):
            log(f"  {lab}: 待っている間に予約の巡回が走った → 走らせない")
            continue
        since = datetime.now()
        if run_task(task):
            wait_cycle(lk, since)
    log("=== 再開チェック終了 ===")
    return 0


if __name__ == "__main__":
    os.chdir(ROOT)
    sys.exit(main(periodic="--periodic" in sys.argv[1:]))
