"""定期処理の順番待ち (2026-10-01 ユーザー確定: 時刻ではなく「間隔と期限」と PC の空きで流す)。

予約タスクで時刻を決め打ちにしていた処理を、表 (job_queue.json) に並べ、
10分おきの見回り (`tick`) が「今、動かしてよい物」を選んで起動する。

  - 間隔   every_hours: 前回うまく終わってから何時間たったら、また動かすか
  - 時間帯 window     : 動かし始めてよい時間 (例 [22, 6] = 22時〜翌6時)。無ければいつでも
  - 空き   need_idle_min: キーボード・マウスが何分触られていなければ動かすか
  - 重さ   heavy       : Chrome を使う重い処理は同時に1本だけ。軽い処理は余力があれば並べる
  - 余力   メモリ使用率 < MEM_MAX % かつ CPU < CPU_MAX % の時だけ新しく始める
  - 期限   deadline_hour: この時刻までに終わっていなければ「期限切れ」として表に出す (黙らない)
  - 待ち   wait_for    : そこに書いた処理が動いている間は始めない (例: バックアップは夜の束の後)
  - 続き   動いている途中で PC が落ちたら、次の見回りでもう一度起動する。
           中の手順は各処理が自分で「済んだ」印を持っている (night_step) ので、続きから進む

記録: 開始・終了を C:/dev/iMak_data/_job_runs.jsonl に1行ずつ (カタログの job_runner と同じ形・全担当で1本)。

使い方:
    python job_queue.py tick           # 見回り (予約から10分おきに呼ぶ)
    python job_queue.py plan           # 今なら何を動かすか (動かさない)
    python job_queue.py status         # 各処理の前回・期限切れ
    python job_queue.py exec <名前>     # 1本を動かして記録する (tick が裏で呼ぶ)
"""
from __future__ import annotations

import ctypes
import datetime as dt
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TABLE_PATH = r"C:/dev/iMak_data/hq/job_queue.json"
STATE_PATH = r"C:/dev/iMak_data/hq/job_queue_state.json"
RUNS_PATH = r"C:/dev/iMak_data/_job_runs.jsonl"
LOG_DIR = r"C:/dev/iMak/iMakHQ/review_logs/job_queue"
MEM_MAX = 75
CPU_MAX = 70


# ---------------------------------------------------------------------------
# 純関数 (テスト対象)
# ---------------------------------------------------------------------------
def in_window(hour, window):
    """動かし始めてよい時間か。window=None はいつでも / [22, 6] は日をまたぐ。"""
    if not window:
        return True
    a, b = window
    return a <= hour < b if a < b else (hour >= a or hour < b)


def is_due(job, st, now):
    """間隔が来ているか。前回うまく終わった時刻 (last_ok) から every_hours 以上。"""
    last = (st or {}).get("last_ok")
    if not last:
        return True
    try:
        return (now - dt.datetime.fromisoformat(last)).total_seconds() >= job["every_hours"] * 3600
    except Exception:
        return True


def overdue(job, st, now):
    """期限切れか: 間隔が来ているのに、今日の期限の時刻を過ぎても終わっていない。"""
    dh = job.get("deadline_hour")
    if dh is None or not is_due(job, st, now):
        return False
    return now.hour >= dh and now.hour < (dh + 12)          # 期限から半日の間だけ「切れ」と出す


def pick(jobs, states, running, now, idle_min, mem_pct, cpu_pct):
    """今起動する処理の名前 list (純関数)。

    running: 今動いている名前の集合。重い処理は同時に1本、軽い処理は余力があれば並べる。
    """
    out = []
    busy_heavy = any(j.get("heavy") for j in jobs if j["name"] in running)
    if mem_pct >= MEM_MAX or cpu_pct >= CPU_MAX:
        return out                                          # 余力が無い = 新しく始めない
    for j in sorted(jobs, key=lambda j: (j.get("deadline_hour") is None, j.get("deadline_hour") or 0)):
        n = j["name"]
        if n in running or not j.get("enabled", True):
            continue
        if not is_due(j, states.get(n), now):
            continue
        if not in_window(now.hour, j.get("window")):
            continue
        if idle_min < j.get("need_idle_min", 0):
            continue
        if any(w in running or w in out for w in j.get("wait_for") or []):   # 同じ回に起動する物も待つ
            continue
        if j.get("heavy"):
            if busy_heavy:
                continue
            busy_heavy = True
        out.append(n)
    return out


# ---------------------------------------------------------------------------
# PC の様子 (I/O)
# ---------------------------------------------------------------------------
def idle_minutes():
    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]
    try:
        li = LASTINPUTINFO()
        li.cbSize = ctypes.sizeof(li)
        ctypes.windll.user32.GetLastInputInfo(ctypes.byref(li))
        return (ctypes.windll.kernel32.GetTickCount() - li.dwTime) / 60000.0
    except Exception:
        return 0.0                                          # 分からない時は「触っている」側


def mem_percent():
    class MS(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("t1", ctypes.c_ulonglong), ("a1", ctypes.c_ulonglong), ("t2", ctypes.c_ulonglong),
                    ("a2", ctypes.c_ulonglong), ("t3", ctypes.c_ulonglong), ("a3", ctypes.c_ulonglong),
                    ("a4", ctypes.c_ulonglong)]
    try:
        m = MS()
        m.dwLength = ctypes.sizeof(m)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        return int(m.dwMemoryLoad)
    except Exception:
        return 100


def cpu_percent():
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command",
                            "(Get-CimInstance Win32_Processor | Measure-Object LoadPercentage -Average).Average"],
                           capture_output=True, text=True, timeout=60,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return int(float(r.stdout.strip() or 100))
    except Exception:
        return 100


def pid_alive(pid):
    try:
        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))   # QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(h)
        return code.value == 259                                          # STILL_ACTIVE
    except Exception:
        return False


# ---------------------------------------------------------------------------
# 表と状態
# ---------------------------------------------------------------------------
def load_jobs():
    return json.load(open(TABLE_PATH, encoding="utf-8"))["jobs"]


def load_states():
    try:
        return json.load(open(STATE_PATH, encoding="utf-8"))
    except Exception:
        return {}


def save_states(st):
    tmp = STATE_PATH + ".tmp"
    json.dump(st, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(tmp, STATE_PATH)


def _update_state(name, **kw):
    st = load_states()
    st.setdefault(name, {}).update(kw)
    save_states(st)


def running_names(states):
    return {n for n, s in states.items() if s.get("pid") and pid_alive(s["pid"])}


# ---------------------------------------------------------------------------
# 実行
# ---------------------------------------------------------------------------
def exec_job(name):
    """1本を動かして、開始・終了を記録する。"""
    job = next(j for j in load_jobs() if j["name"] == name)
    os.makedirs(LOG_DIR, exist_ok=True)
    start = dt.datetime.now()
    log = os.path.join(LOG_DIR, f"{name}_{start:%Y%m%d}.log")
    _update_state(name, pid=os.getpid(), last_start=start.isoformat(timespec="seconds"))
    cmd = job["cmd"]
    if cmd[0].lower().endswith(".bat"):
        cmd = ["cmd", "/c"] + cmd
    with open(log, "a", encoding="utf-8") as f:
        f.write(f"\n===== {start:%Y-%m-%d %H:%M:%S} 開始 =====\n")
        f.flush()
        rc = subprocess.call(cmd, stdout=f, stderr=subprocess.STDOUT, cwd=job.get("cwd") or HERE,
                             env=dict(os.environ, PYTHONIOENCODING="utf-8"),
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    end = dt.datetime.now()
    kw = {"pid": None, "last_end": end.isoformat(timespec="seconds"), "last_rc": rc}
    # 束ねたバッチ (夜の束など) は中の手順が自分で失敗を記録・再挑戦するので、最後まで走れば「済んだ」とする。
    # 途中で PC が落ちた時だけ (= ここまで来ない) 次の見回りで続きから起動される
    if rc == 0 or job.get("any_rc_ok"):
        kw["last_ok"] = start.isoformat(timespec="seconds")
    _update_state(name, **kw)
    rec = {"owner": "HQ", "job": name, "start": start.isoformat(timespec="seconds"),
           "end": end.isoformat(timespec="seconds"), "sec": int((end - start).total_seconds()), "rc": rc,
           "chrome": bool(job.get("heavy")), "every_days": round(job["every_hours"] / 24, 2),
           "deadline_hour": job.get("deadline_hour"), "log": log}
    with open(RUNS_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rc


def _spawn(name):
    flags = 0x00000008 | 0x00000200 | getattr(subprocess, "CREATE_NO_WINDOW", 0)   # DETACHED | NEW_GROUP
    subprocess.Popen([sys.executable, os.path.abspath(__file__), "exec", name], cwd=HERE,
                     creationflags=flags, close_fds=True)


def tick(dry=False):
    jobs = load_jobs()
    states = load_states()
    run = running_names(states)
    # 途中で止まった物 (pid が書いてあるのに動いていない) は印を消す = 次の見回りで続きから
    for n, s in states.items():
        if s.get("pid") and n not in run:
            s["pid"] = None
            s["last_rc"] = "interrupted"
    if not dry:
        save_states(states)
    now = dt.datetime.now()
    idle, mem, cpu = idle_minutes(), mem_percent(), cpu_percent()
    todo = pick(jobs, states, run, now, idle, mem, cpu)
    late = [j["name"] for j in jobs if j.get("enabled", True) and j["name"] not in run
            and overdue(j, states.get(j["name"]), now)]
    print(f"[{now:%m/%d %H:%M}] 触っていない {idle:.0f}分 / メモリ {mem}% / CPU {cpu}% / "
          f"動作中 {sorted(run) or 'なし'} / 起動 {todo or 'なし'}" + (f" / ⚠期限切れ {late}" if late else ""))
    st = load_states()
    st["_tick"] = {"at": now.isoformat(timespec="seconds"), "late": late, "started": todo}
    if not dry:
        save_states(st)
        for n in todo:
            _spawn(n)
            time.sleep(2)
    return todo


def status():
    jobs, st = load_jobs(), load_states()
    now = dt.datetime.now()
    for j in jobs:
        s = st.get(j["name"]) or {}
        print(f"{j['name']:16} 前回OK {s.get('last_ok') or '-':19} 前回rc {str(s.get('last_rc')):11} "
              f"{'動作中' if s.get('pid') and pid_alive(s['pid']) else ''}"
              f"{' ⚠期限切れ' if overdue(j, s, now) else ''}")
    print(f"最後の見回り: {(st.get('_tick') or {}).get('at')}")


def main():
    a = sys.argv[1:]
    if not a:
        print(__doc__)
        return 0
    if a[0] == "tick":
        tick()
    elif a[0] == "plan":
        tick(dry=True)
    elif a[0] == "status":
        status()
    elif a[0] == "exec":
        return exec_job(a[1])
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
