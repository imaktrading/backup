# -*- coding: utf-8 -*-
"""カタログの定期処理を1本の口から走らせ、開始・終了を1行残す (2026-10-01).

依頼: `requests/2026-10-01_night_jobs_slimming_go.md` [IMPLEMENT-GO] 項4・5

## なぜ

予約から直に python を呼んでいたので、**終わった記録がどこにも無かった**。
HQ が夜の落ち方を調べた図で、カタログの処理が全部 ◆ (終わりが不明) になっていた。
ログも `>>` の追記で伸び続けていた (set_name_audit_daily.log が 2.4MB / 19,520行)。

## 何をするか

    python tools/job_runner.py <名前>     1本走らせて記録する
    python tools/job_runner.py --list     表を JSON で出す (2台で流す仕組みが読む用)
    python tools/job_runner.py --due      間隔が来ている物の名前だけ出す

記録は **全担当で1本** `C:/dev/iMak_data/_job_runs.jsonl`:

    {"owner":"CATALOG","job":"set_name_audit","start":"...","end":"...","sec":23,"rc":0}

★**時刻を持たない。** 持つのは `every_days` (間隔) と `deadline_days` (これを超えたら遅れ) と
  `chrome` (Chrome を使う = 重い) だけ。どの機械のどの時刻で流すかは呼ぶ側が決める
  (2026-10-01 ユーザー確定「時刻ではなく間隔と期限で持つ」)。

★ログは日付で切り、**14日より古いものを消す**。
★1本が落ちても後ろを止めない (呼ぶ側が順に呼ぶ作り)。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNS = Path("C:/dev/iMak_data/_job_runs.jsonl")
LOGS = Path("C:/dev/iMak_data/catalog/_job_logs")
OWNER = "CATALOG"
KEEP_LOG_DAYS = 14

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# every_days = 間隔 / deadline_days = これを超えたら遅れ / chrome = 画面つきブラウザを使う
JOBS: dict[str, dict] = {
    "prune_missing_models": {
        "cmd": ["prune_missing_models.py"], "every_days": 1, "deadline_days": 3,
        "chrome": False, "note": "missing_models.csv と pdca.db の掃除 (読み手 HQ)"},
    "set_name_audit": {
        "cmd": ["tools/set_name_integrity_audit.py", "--cat", "all"],
        "every_days": 1, "deadline_days": 3, "chrome": False,
        "note": "見張り項目を 0 で維持 + 共有の表を写す"},
    "character_audit": {
        "cmd": ["tools/character_value_audit.py"], "every_days": 1, "deadline_days": 7,
        "chrome": False, "note": "C:Character の綴りのゆれ (一覧の取り直しは7日ごと)"},
    "ingest_watch": {
        "cmd": ["tools/scheduled_ingest_watch.py"], "every_days": 1, "deadline_days": 3,
        "chrome": False, "note": "走っていない取り込みを依頼書にする"},
    "tcg_monthly": {
        "cmd": ["tools/tcg_monthly.py"], "every_days": 30, "deadline_days": 45,
        "chrome": False, "note": "TCG の新弾取り込み + 公式突合 + 検収 (約60分)"},
}

# ★UNIQLO 月次は **1本に通さない**。20工程を1本で走らせると、途中で機械が落ちた分から
#   先が翌月まで動かない (2026-10-01 の 4:00 の走行がそれで消えた)。
#   `uniqlo_monthly.STEPS` を1工程=1ジョブに割って、1つずつ記録しながら流す。
#   ユーザー指示 2026-10-01「途中で落ちるで」。
def _load_uniqlo_steps() -> None:
    import importlib.util
    spec = importlib.util.spec_from_file_location("_um", ROOT / "tools" / "uniqlo_monthly.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    for i, (name, cmd) in enumerate(m.STEPS, 1):
        JOBS[f"ut{i:02d}_{_slug(cmd[0])}"] = {
            "cmd": list(cmd), "every_days": 30, "deadline_days": 45,
            "chrome": "sizechart" in cmd[0] or "discover" in cmd[0],
            "note": f"UNIQLO 月次 {i}/{len(m.STEPS)}: {name}"}


def _slug(path: str) -> str:
    return path.rsplit("/", 1)[-1].replace(".py", "")


_load_uniqlo_steps()


def _runs() -> list[dict]:
    if not RUNS.exists():
        return []
    out = []
    for line in RUNS.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except ValueError:
            continue          # 1行壊れても残りを読む
    return out


def last_ok(job: str) -> datetime | None:
    """最後に rc=0 で終わった時刻 (無ければ None)."""
    best = None
    for r in _runs():
        if r.get("owner") != OWNER or r.get("job") != job or r.get("rc") != 0:
            continue
        try:
            t = datetime.fromisoformat(r["end"])
        except (KeyError, ValueError):
            continue
        if best is None or t > best:
            best = t
    return best


def due(job: str) -> bool:
    t = last_ok(job)
    if t is None:
        return True
    return datetime.now() - t >= timedelta(days=JOBS[job]["every_days"])


def _prune_logs() -> None:
    limit = time.time() - KEEP_LOG_DAYS * 86400
    for p in LOGS.glob("*.log"):
        try:
            if p.stat().st_mtime < limit:
                p.unlink()
        except OSError:
            pass


def run(job: str) -> int:
    spec = JOBS[job]
    LOGS.mkdir(parents=True, exist_ok=True)
    _prune_logs()
    log = LOGS / f"{job}_{datetime.now():%Y%m%d}.log"
    start = datetime.now()
    t0 = time.time()
    print(f"=== {job} 開始 {start:%Y-%m-%d %H:%M:%S} ===", flush=True)
    try:
        r = subprocess.run([sys.executable] + [str(x) for x in spec["cmd"]],
                           cwd=str(ROOT), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=8 * 3600)
        rc, body = r.returncode, (r.stdout or "") + (r.stderr or "")
    except Exception as e:                      # 落ちても記録は残す
        rc, body = -1, f"{type(e).__name__}: {e}"
    sec = int(time.time() - t0)
    end = datetime.now()
    with log.open("a", encoding="utf-8") as f:
        f.write(f"=== {job} {start:%Y-%m-%d %H:%M:%S} → {end:%H:%M:%S} ({sec}秒) rc={rc} ===\n")
        f.write(body + "\n")
    RUNS.parent.mkdir(parents=True, exist_ok=True)
    with RUNS.open("a", encoding="utf-8") as f:
        f.write(json.dumps({
            "owner": OWNER, "job": job, "start": start.isoformat(timespec="seconds"),
            "end": end.isoformat(timespec="seconds"), "sec": sec, "rc": rc,
            "chrome": spec["chrome"], "every_days": spec["every_days"],
            "deadline_days": spec["deadline_days"], "log": str(log),
        }, ensure_ascii=False) + "\n")
    print(f"=== {job} 終わり {end:%H:%M:%S} ({sec}秒) rc={rc} / 記録 {log} ===", flush=True)
    return rc


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("job", nargs="?")
    ap.add_argument("--list", action="store_true", help="表を JSON で出す")
    ap.add_argument("--due", action="store_true", help="間隔が来ている物の名前")
    ap.add_argument("--run-due", metavar="接頭辞",
                    help="間隔が来ている物を **1つずつ** 走らせる (例 ut)")
    ap.add_argument("--budget-min", type=int, default=120,
                    help="--run-due の持ち時間 (分)。使い切ったらそこで止める")
    a = ap.parse_args()

    if a.list:
        rows = []
        for k, v in JOBS.items():
            t = last_ok(k)
            rows.append({"owner": OWNER, "job": k, "every_days": v["every_days"],
                         "deadline_days": v["deadline_days"], "chrome": v["chrome"],
                         "note": v["note"],
                         "last_ok": t.isoformat(timespec="seconds") if t else None,
                         "due": due(k)})
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0
    if a.due:
        for k in JOBS:
            if due(k):
                print(k)
        return 0
    if a.run_due:
        # ★1工程ずつ。1本落ちても後ろを止めない。持ち時間を使い切ったら残りは次回。
        #   どこまで済んだかは _job_runs.jsonl が持つので、落ちても同じ所からは繰り返さない。
        names = [k for k in JOBS if k.startswith(a.run_due) and due(k)]
        print(f"{a.run_due}* で間隔が来ているもの {len(names)}件 / 持ち時間 {a.budget_min}分")
        t0 = time.time()
        done = ng = 0
        for k in names:
            if (time.time() - t0) / 60 >= a.budget_min:
                print(f"持ち時間を使い切った。残り {len(names) - done - ng}件 は次回")
                break
            rc = run(k)
            if rc == 0:
                done += 1
            else:
                ng += 1
        print(f"済み {done} / 落ちた {ng} / 残り {len(names) - done - ng}")
        return 0
    if not a.job or a.job not in JOBS:
        print("名前: " + " / ".join(JOBS))
        return 2
    return run(a.job)


if __name__ == "__main__":
    sys.exit(main())
