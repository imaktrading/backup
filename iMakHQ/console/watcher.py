# -*- coding: utf-8 -*-
"""監視くんの巡回を見張る (2026-09-16 ユーザー「その時間帯は軽め作業にするから、
次回開始時間と終了予定時間がわかれば」)。

★なぜ自前で記録するのか: Windows のタスク履歴ログ (TaskScheduler/Operational) は
  **無効** で、過去の所要時間が取れない。なので Console が定期的に見て、
  巡回の開始と終了を自分で書き留め、その平均から「終了めやす」を出す。
  記録先 C:/dev/iMak_data/hq/watcher_runs.json (共有領域。他の worktree は触らない)。

巡回中かどうかは **プロセス** を見て決める (run_cycle.py が動いていれば巡回中)。
次回の開始時刻は Windows のタスクから取る。
"""
import datetime
import json
import os

RUNS_PATH = r"C:/dev/iMak_data/hq/watcher_runs.json"
KEEP_RUNS = 20                      # 平均を出すのに残す回数

# 見張る対象: タスク名 → 画面に出す名前
TASKS = {
    "iMakInventory_Cycle": "監視くん 巡回 (HIGH)",
    "iMakInventory_Cycle_LOW": "監視くん 巡回 (LOW)",
    "iMakInventory_Monitor_Daily": "監視くん 日次",
}
# プロセスのコマンドラインから、どのタスクの巡回かを見分ける手掛かり
PROC_HINTS = (("--sheet low", "iMakInventory_Cycle_LOW"),
              ("--sheet-id", "iMakInventory_Cycle"),
              ("monitor", "iMakInventory_Monitor_Daily"))


def task_of_cmdline(cmdline):
    """巡回プロセスのコマンドライン → タスク名 (分からなければ None)。純関数。"""
    c = (cmdline or "").lower()
    if "run_cycle" not in c and "monitor" not in c:
        return None
    for hint, task in PROC_HINTS:
        if hint in c:
            return task
    return "iMakInventory_Cycle"


def _parse(ts):
    try:
        return datetime.datetime.fromisoformat(str(ts)[:19])
    except (TypeError, ValueError):
        return None


def update_runs(runs, running_now, now):
    """巡回の開始・終了を記録する (純関数)。

    runs        … {タスク名: {"open": 開始iso or None, "done": [{"start","end","min"}]}}
    running_now … {タスク名: 開始時刻(datetime)}  … 今 走っている巡回
    戻り: 更新した runs
    """
    runs = dict(runs or {})
    for task in set(list(runs.keys()) + list(running_now.keys())):
        rec = dict(runs.get(task) or {})
        rec.setdefault("done", [])
        started = running_now.get(task)
        if started:                                    # 走っている
            rec["open"] = started.isoformat(timespec="seconds")
        elif rec.get("open"):                          # さっきまで走っていた = 終わった
            s = _parse(rec["open"])
            if s and now > s:
                mins = round((now - s).total_seconds() / 60)
                if 1 <= mins <= 24 * 60:               # 桁のおかしい記録は残さない
                    rec["done"] = (rec["done"] + [{"start": rec["open"],
                                                   "end": now.isoformat(timespec="seconds"),
                                                   "min": mins}])[-KEEP_RUNS:]
            rec["open"] = None
        runs[task] = rec
    return runs


def average_minutes(rec):
    """その巡回がだいたい何分かかるか (記録が無ければ None)。純関数。"""
    mins = [r.get("min") for r in (rec or {}).get("done", []) if r.get("min")]
    return round(sum(mins) / len(mins)) if mins else None


def status(runs, running_now, next_runs, now):
    """画面に出す形 (純関数)。

    next_runs … {タスク名: 次回開始(datetime or None)}
    戻り: [{name, label, running, started, avg_min, eta, left_min, next, next_in_min}]
    """
    out = []
    for task, label in TASKS.items():
        rec = runs.get(task) or {}
        avg = average_minutes(rec)
        started = running_now.get(task)
        row = {"name": task, "label": label, "running": bool(started), "avg_min": avg,
               "runs": len(rec.get("done") or [])}
        if started:
            row["started"] = started.strftime("%H:%M")
            if avg:
                eta = started + datetime.timedelta(minutes=avg)
                row["eta"] = eta.strftime("%H:%M")
                row["left_min"] = max(0, round((eta - now).total_seconds() / 60))
        nxt = next_runs.get(task)
        if nxt:
            row["next"] = nxt.strftime("%m/%d %H:%M")
            row["next_in_min"] = round((nxt - now).total_seconds() / 60)
            if avg:
                row["next_eta"] = (nxt + datetime.timedelta(minutes=avg)).strftime("%H:%M")
        out.append(row)
    out.sort(key=lambda r: (not r["running"], r.get("next_in_min") if r.get("next_in_min") is not None else 10 ** 9))
    return out


def _span(r):
    """1本の巡回の時間帯 ("19:30〜21:00" / 所要が分からなければ "19:30〜")。純関数。"""
    hm = (r.get("next") or "").split(" ")[-1]
    return hm + "〜" + (r.get("next_eta") or "")


def headline(rows, now=None):
    """画面の1行 (純関数)。

    ★2026-09-16 ユーザー「〜22:45 の表示がないけど」: 一番近い1本しか出していなかった。
      **このあと控えている巡回を全部**出す (時間帯で分かるように)。
    """
    # 今走っている本人と、時刻が過ぎている物は「このあと」に出さない
    nxt = sorted([r for r in rows if r.get("next_in_min") is not None
                  and not r["running"] and r["next_in_min"] > 0],
                 key=lambda x: x["next_in_min"])

    def _tail(skip):
        later = " / ".join(_span(r) for r in nxt[skip:skip + 3])
        return ("  このあと " + later) if later else ""

    run = [r for r in rows if r["running"]]
    if run:
        r = run[0]
        # 走っている時は、控えている巡回を **1本目から** 全部出す
        if r.get("eta"):
            return ("巡回中 %s〜%s (あと約%d分) — 重い作業は避ける%s"
                    % (r["started"], r["eta"], r.get("left_min", 0), _tail(0)))
        return "巡回中 %s〜 (所要はまだ分かりません) — 重い作業は避ける%s" % (r["started"], _tail(0))
    if not nxt:
        return "巡回の予定が読めません"
    tail = _tail(1)                                   # 先頭は見出しに出すので、2本目から
    r = nxt[0]
    hm = r["next"].split(" ")[-1]
    when = ("まもなく" if r["next_in_min"] <= 0
            else ("あと%d分" % r["next_in_min"]) if r["next_in_min"] < 60
            else "あと%.1f時間" % (r["next_in_min"] / 60.0))
    head = "次の巡回 %s〜%s (%s)" % (hm, r.get("next_eta") or "", when)
    if not r.get("next_eta"):
        head += " ※所要はまだ記録中"
    return head + tail


def load_runs(path=RUNS_PATH):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_runs(runs, path=RUNS_PATH):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(runs, f, ensure_ascii=False, indent=1)
    except OSError:
        pass
