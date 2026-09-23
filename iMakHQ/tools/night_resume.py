#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PC が落ちて立ち上がった時、途中で止まった夜間バッチの続きを走らせる (2026-09-24)。

★ユーザー判断 (2026-09-24):「落ちる前提でやるしかない。途中から再開できるようにしておけば」。
  この PC は落ちた後に自動ログインする (AutoAdminLogon=1)。ログオン時の予約からこれを呼ぶ。

各バッチは night_step.py で手順ごとに「済んだ」印を付けている。ここでは:
  - 途中で止まった走行 (finished でない・20時間以内) があり
  - そのバッチが今は動いていない
なら、バッチをもう一度起動する。済んだ手順はバッチ側 (night_step --check) が飛ばす。

使い方:
    python night_resume.py            # 再開する
    python night_resume.py --dry-run  # 何を再開するかだけ出す
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import night_step as NS                                        # noqa: E402

TOOLS = os.path.dirname(os.path.abspath(__file__))
RUN_MIN = r"C:\dev\iMak_data\tools\run_min.vbs"
# job 名 → バッチ
JOBS = {
    "hoju": os.path.join(TOOLS, "run_hoju_search.bat"),
    "psawarm": os.path.join(TOOLS, "run_psa_cache_warm.bat"),
}
LOG = r"C:\dev\iMak\iMakHQ\review_logs\night_resume.log"


def running_batches():
    """今動いているバッチのファイル名 (小文字) の集合 (I/O)。"""
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process | ForEach-Object { $_.CommandLine }"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60).stdout
    except Exception:                                          # noqa: BLE001
        return None                                            # 分からない時は再開しない
    return {os.path.basename(p).lower() for p in JOBS.values() if os.path.basename(p).lower() in out.lower()}


def plan(states, running):
    """再開するバッチの一覧 (純関数)。running が None (判らない) なら何もしない。"""
    if running is None:
        return []
    return [job for job, st in states.items()
            if NS.is_resumable(st) and os.path.basename(JOBS[job]).lower() not in running]


def main(argv):
    dry = "--dry-run" in argv
    states = {job: NS.load(job) for job in JOBS}
    todo = plan(states, running_batches())
    lines = []
    for job in todo:
        st = states[job]
        done = sum(1 for v in (st.get("steps") or {}).values() if v.get("status") == "done")
        lines.append(f"{NS._now():%Y-%m-%d %H:%M:%S} [resume] {job}: {st.get('started_at')} の走行が途中 "
                     f"(済み {done}手順) → 続きを起動")
        if not dry:
            subprocess.Popen(["wscript.exe", "//nologo", RUN_MIN, JOBS[job]],
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if not todo:
        lines.append(f"{NS._now():%Y-%m-%d %H:%M:%S} [resume] 途中で止まった夜間バッチはありません")
    for ln in lines:
        print(ln)
    if not dry:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
