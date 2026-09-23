#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""夜間バッチを「手順ごとに済んだ印を付けて」走らせる。PC が落ちても続きから再開できる (2026-09-24)。

★ユーザー判断 (2026-09-24):「落ちる前提でやるしかない。途中で落ちても、最初からではなくて
  途中から再開できるようにしておけば」。作業 PC が 9/16 から1日数回落ちており、原因を追い切れない。

使い方 (バッチの各行をこれで包む):
    python -u night_step.py <job> --begin          … その晩の走行を始める (続きがあれば続きにする)
    python -u night_step.py <job> <step> -- <python の引数...>
    python -u night_step.py <job> <step> --no-retry -- <...>   … eBay に書く手順
    python -u night_step.py <job> --end            … 最後まで走った印

手順の扱い:
  - 済んだ手順 (done) は飛ばす
  - 途中で落ちた手順 (running のまま) は、もう一度やる。ただし --no-retry の手順は
    **やり直さず「要確認」と出して飛ばす** (二重に eBay へ送らないため)
  - 同じ手順が2回続けて途中で落ちたら、それ以上やらない (その手順が落とす原因なら無限に落ちる)
  - 前の走行が最後まで行っていて、20時間を超えて古ければ、新しい走行として最初から

起動した時の再開は night_resume.py が行う (落ちた後の自動ログインで走る予約から)。
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta

STATE_DIR = r"C:/dev/iMak_data/hq/night_state"
RESUME_WINDOW = timedelta(hours=20)
MAX_ATTEMPTS = 2


def state_path(job, d=STATE_DIR):
    return os.path.join(d, f"{job}.json")


def load(job, d=STATE_DIR):
    try:
        with open(state_path(job, d), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save(job, st, d=STATE_DIR):
    os.makedirs(d, exist_ok=True)
    tmp = state_path(job, d) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)
    os.replace(tmp, state_path(job, d))


def _now():
    return datetime.now()


def is_resumable(st, now=None):
    """途中で止まった走行で、まだ続きをやる価値があるか (純関数)。"""
    now = now or _now()
    if not st or st.get("finished"):
        return False
    try:
        started = datetime.fromisoformat(st.get("started_at", ""))
    except ValueError:
        return False
    return now - started <= RESUME_WINDOW


def begin(st, now=None):
    """走行の始まり (純関数)。続きがあれば続き、無ければ新しい走行。戻り (state, resumed?)"""
    now = now or _now()
    if is_resumable(st, now):
        st = dict(st)
        st["resumes"] = int(st.get("resumes", 0)) + 1
        st["last_resume_at"] = now.isoformat(timespec="seconds")
        return st, True
    return {"started_at": now.isoformat(timespec="seconds"), "finished": False,
            "resumes": 0, "steps": {}}, False


def decide(st, step, no_retry=False):
    """この手順をどうするか (純関数)。'run' / 'skip_done' / 'skip_interrupted' / 'skip_loop'"""
    s = (st.get("steps") or {}).get(step) or {}
    status = s.get("status")
    if status == "done":
        return "skip_done"
    if status == "running":                     # 前回この手順の最中に落ちた
        if no_retry:
            return "skip_interrupted"
        if int(s.get("attempts", 0)) >= MAX_ATTEMPTS:
            return "skip_loop"
    return "run"


def _explain_skip(st, job, step, what):
    if what == "skip_done":
        print(f"[skip] {step}: 前回の走行で済んでいる")
        return
    if what == "skip_interrupted":
        print(f"⚠️要対応 [skip] {step}: 前回この手順の最中に PC が落ちた。eBay に書く/メールを送る"
              f"手順なので、二重送信を避けて自動ではやり直さない (次の晩に通常どおり走る)")
        st["steps"][step]["status"] = "interrupted"
    else:
        print(f"⚠️要対応 [skip] {step}: {MAX_ATTEMPTS}回続けてこの手順の最中に落ちた。"
              f"この手順が落とす原因の疑いがあるので飛ばす")
        st["steps"][step]["status"] = "gave_up"
    save(job, st)


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    job = argv[0]
    if argv[1] == "--begin":
        st, resumed = begin(load(job))
        save(job, st)
        if resumed:
            done = [k for k, v in st["steps"].items() if v.get("status") == "done"]
            print(f"[resume] {job}: 前回 {st['started_at']} の続きから再開 "
                  f"(済み {len(done)}手順は飛ばす / 再開 {st['resumes']}回目)")
        else:
            print(f"[begin] {job}: 新しい走行 {st['started_at']}")
        return 0
    if argv[1] == "--end":
        st = load(job)
        st["finished"] = True
        st["finished_at"] = _now().isoformat(timespec="seconds")
        save(job, st)
        return 0

    step = argv[1]
    rest = argv[2:]
    # バッチ用: 元の行はそのまま残し、前後に --check / --done を挟む形
    #   python -u night_step.py hoju <step> --check [--no-retry] || goto :skipN
    #   python -u 元の行 ...
    #   python -u night_step.py hoju <step> --done %errorlevel%
    if rest and rest[0] == "--check":
        st = load(job)
        if not st:
            st, _ = begin({})
        what = decide(st, step, "--no-retry" in rest)
        if what != "run":
            _explain_skip(st, job, step, what)
            return 1                                 # 1 = 飛ばす (バッチ側で goto)
        s = st.setdefault("steps", {}).setdefault(step, {})
        s.update({"status": "running", "attempts": int(s.get("attempts", 0)) + 1,
                  "at": _now().isoformat(timespec="seconds")})
        save(job, st)
        return 0
    if rest and rest[0] == "--done":
        rc = int(rest[1]) if len(rest) > 1 and rest[1].lstrip("-").isdigit() else 0
        st = load(job)
        st.setdefault("steps", {}).setdefault(step, {}).update(
            {"status": "done" if rc == 0 else "failed", "rc": rc,
             "end": _now().isoformat(timespec="seconds")})
        save(job, st)
        return 0
    no_retry = False
    if rest and rest[0] == "--no-retry":
        no_retry, rest = True, rest[1:]
    if rest and rest[0] == "--":
        rest = rest[1:]
    st = load(job)
    if not st:                                   # --begin 無しで呼ばれた = 従来どおり走らせる
        st, _ = begin({})
    what = decide(st, step, no_retry)
    if what != "run":
        _explain_skip(st, job, step, what)
        return 0
    s = st.setdefault("steps", {}).setdefault(step, {})
    s.update({"status": "running", "attempts": int(s.get("attempts", 0)) + 1,
              "at": _now().isoformat(timespec="seconds")})
    save(job, st)
    rc = subprocess.call([sys.executable, "-u"] + rest)
    st = load(job)
    st["steps"][step].update({"status": "done" if rc == 0 else "failed", "rc": rc,
                              "end": _now().isoformat(timespec="seconds")})
    save(job, st)
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
