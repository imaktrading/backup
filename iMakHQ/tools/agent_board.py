# -*- coding: utf-8 -*-
"""担当ボード — 各 PC の Claude の窓がいま何をしているか (2026-09-29 ユーザー確定)。

## 何を出すか

窓ごとに 状態 (作業中 / 返事待ち / 待機中)・今やっていること・経過・直近60分の動き・
claude.ai/code の会話の住所。住所があるので、Console の行を押すとその会話が開いて**そのまま打てる**
(見るだけの画面は意味がない、とユーザー指摘 2026-09-29)。

## どこから読むか

- この PC: `claude agents --json` (窓の一覧と busy/idle) + 各窓の会話記録
  `~/.claude/projects/*/<sessionId>.jsonl` の末尾だけ。
  会話の住所は記録の `bridge-session` 行 (`cse_XXX` → `https://claude.ai/code/session_XXX`)
- 別の PC (LAPTOP): 向こうの記録はこの PC から見えないので、向こうで `push` を5分ごとに回し、
  「既存メンテ」スプシのタブ `担当_<PC名>` に書いてもらう。Console はそれを読む。
  PC ごとに別タブなのは、両方が同じタブを丸ごと書き換えて消し合わないため

## 使い方

    python agent_board.py show     # この PC の分を表示
    python agent_board.py push     # この PC の分をスプシのタブ 担当_<PC名> に書く (LAPTOP で5分ごと)

★`claude agents` を窓なしで呼ぶ時は DISABLE_AUTOUPDATER=1 を付ける。
  2026-09-29、素の `claude agents` が起動をきっかけに新しい版 (2.1.284) を入れてしまった
  (この PC は 2.1.281 固定。claude_rc.cmd 参照)。
"""
from __future__ import annotations

import datetime as _dt
import glob
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

PROJECTS = os.path.expanduser("~/.claude/projects")
TAIL_BYTES = 600_000          # 記録の末尾だけ読む (長い会話は数十MBになる)
BUCKET_MIN, BUCKETS = 5, 12   # 直近60分を5分ずつ
REMOTE_HOSTS = ("LAPTOP",)
TAB_PREFIX = "担当_"
HEADER = ["更新", "名前", "状態", "今", "から", "起動", "会話", "動き", "場所"]
STALE_MIN = 15                # 別PCの書込がこれより古ければ「不明」


def host():
    return (os.environ.get("COMPUTERNAME") or "").upper() or "THIS-PC"


# ------------------------------------------------------------------ 記録を読む (純関数)

def _parse_ts(s):
    """記録の時刻 (UTC の ISO) → この PC の時刻 (naive)。読めなければ None。"""
    if not s:
        return None
    try:
        t = _dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo:
        t = t.astimezone().replace(tzinfo=None)
    return t


def _tool_line(name, inp):
    """道具を使った1回を、人が読む1行にする。"""
    inp = inp or {}
    d = (inp.get("description") or "").strip()
    if d:
        return d
    fp = inp.get("file_path") or inp.get("path") or ""
    base = os.path.basename(str(fp)) if fp else ""
    label = {"Read": "読む", "Edit": "直す", "Write": "書く", "Grep": "探す", "Glob": "探す",
             "WebSearch": "ネットで調べる", "WebFetch": "ページを読む",
             "SendMessage": "他の担当に連絡"}.get(name, name)
    if name == "WebSearch" and inp.get("query"):
        return "ネットで調べる: " + str(inp["query"])[:60]
    return (label + " " + base).strip()


def _first_line(text, n=90):
    for ln in str(text or "").splitlines():
        ln = ln.strip().lstrip("#*- ").strip()
        if ln:
            return ln if len(ln) <= n else ln[:n - 1] + "…"
    return ""


def _is_prompt(d):
    """人 (または他の担当) からの発言か。道具の結果は除く。"""
    if d.get("type") != "user" or d.get("isMeta"):
        return False
    c = (d.get("message") or {}).get("content")
    if isinstance(c, str):
        return True
    if isinstance(c, list):
        return any(isinstance(x, dict) and x.get("type") == "text" for x in c) and \
            not any(isinstance(x, dict) and x.get("type") == "tool_result" for x in c)
    return False


def summarize(lines, now=None):
    """記録の行 (dict の列) → {now, last_text, asked, since_prompt, last_at, act, url, name}。

    now は「今」(テストで固定する)。act は直近60分の道具の回数 (古い→新しい, 5分ずつ)。
    """
    now = now or _dt.datetime.now()
    out = {"now": "", "last_text": "", "asked": False, "since_prompt": None, "last_at": None,
           "act": [0] * BUCKETS, "url": "", "name": ""}
    last_kind = None
    for d in lines:
        t = d.get("type")
        if t == "bridge-session" and d.get("bridgeSessionId"):
            bid = str(d["bridgeSessionId"])
            out["url"] = "https://claude.ai/code/session_" + bid.split("_", 1)[-1]
            continue
        if t == "agent-name" and d.get("agentName"):
            out["name"] = d["agentName"]
            continue
        ts = _parse_ts(d.get("timestamp"))
        if _is_prompt(d):
            out["since_prompt"] = ts or out["since_prompt"]
            last_kind = "prompt"
            continue
        if t != "assistant" or d.get("isSidechain"):
            continue
        for x in (d.get("message") or {}).get("content") or []:
            if not isinstance(x, dict):
                continue
            if x.get("type") == "tool_use":
                out["now"] = _tool_line(x.get("name"), x.get("input"))
                last_kind = "tool"
                if ts:
                    age = (now - ts).total_seconds() / 60
                    if 0 <= age < BUCKET_MIN * BUCKETS:
                        out["act"][BUCKETS - 1 - int(age // BUCKET_MIN)] += 1
            elif x.get("type") == "text" and (x.get("text") or "").strip():
                out["last_text"] = x["text"]
                last_kind = "text"
        if ts:
            out["last_at"] = ts
    if last_kind == "text":
        tail = out["last_text"].strip()[-160:]
        out["asked"] = ("？" in tail) or tail.endswith("?")
        out["now"] = _first_line(out["last_text"])
    return out


def state_of(status, s):
    """claude agents の busy/idle と記録から 作業中 / 返事待ち / 待機中 を決める (純関数)。"""
    if status == "busy":
        return "busy"
    return "ask" if s.get("asked") else "idle"


def read_tail(path, nbytes=TAIL_BYTES):
    """記録の末尾だけ dict の列で返す (I/O)。途中から読むので最初の1行は捨てる。"""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            if size > nbytes:
                f.seek(size - nbytes)
                f.readline()
            raw = f.read().decode("utf-8", "ignore")
    except OSError:
        return []
    out = []
    for ln in raw.splitlines():
        try:
            out.append(json.loads(ln))
        except ValueError:
            continue
    return out


def _find_transcript(session_id):
    hits = glob.glob(os.path.join(PROJECTS, "*", session_id + ".jsonl"))
    return max(hits, key=os.path.getmtime) if hits else None


# ------------------------------------------------------------------ この PC の一覧 (I/O)

def list_windows():
    """`claude agents --json` の結果。取れなければ []。"""
    env = dict(os.environ, DISABLE_AUTOUPDATER="1")
    try:
        r = subprocess.run(["claude", "agents", "--json"], capture_output=True, text=True,
                           encoding="utf-8", errors="ignore", timeout=20, env=env,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), shell=False)
        return json.loads(r.stdout or "[]")
    except Exception:                                          # noqa: BLE001 取れなければ空
        return []


def local_agents(now=None):
    now = now or _dt.datetime.now()
    rows = []
    for w in list_windows():
        sid = w.get("sessionId") or ""
        path = _find_transcript(sid) if sid else None
        s = summarize(read_tail(path), now) if path else summarize([], now)
        st = state_of(w.get("status"), s)
        since = s["since_prompt"] if st == "busy" else (s["last_at"] or s["since_prompt"])
        started = None
        if w.get("startedAt"):
            started = _dt.datetime.fromtimestamp(int(w["startedAt"]) / 1000)
        rows.append({"name": w.get("name") or s["name"] or sid[:8], "state": st, "now": s["now"],
                     "since": since.isoformat(timespec="seconds") if since else "",
                     "started": started.isoformat(timespec="seconds") if started else "",
                     "url": s["url"], "act": s["act"],
                     "where": os.path.basename((w.get("cwd") or "").rstrip("\\/"))})
    order = {"ask": 0, "busy": 1, "idle": 2}
    rows.sort(key=lambda r: (order.get(r["state"], 3), r["name"]))
    return rows


# ------------------------------------------------------------------ 別の PC と受け渡し

def to_sheet_rows(rows, at):
    """この PC の一覧 → タブに書く2次元配列 (純関数)。"""
    out = [HEADER]
    for r in rows:
        out.append([at, r["name"], r["state"], r["now"], r["since"], r["started"], r["url"],
                    ",".join(str(x) for x in r["act"]), r["where"]])
    return out


def from_sheet_rows(rows2d, now=None):
    """タブの2次元配列 → {at, stale, rows} (純関数)。古い書込は stale=True。"""
    now = now or _dt.datetime.now()
    body = [r for r in (rows2d or [])[1:] if r and len(r) >= 3 and r[1]]
    at = None
    rows = []
    for r in body:
        r = list(r) + [""] * (len(HEADER) - len(r))
        try:
            at = at or _dt.datetime.fromisoformat(r[0])
        except ValueError:
            pass
        try:
            act = [int(x) for x in r[7].split(",") if x != ""]
        except ValueError:
            act = []
        rows.append({"name": r[1], "state": r[2], "now": r[3], "since": r[4], "started": r[5],
                     "url": r[6], "act": act or [0] * BUCKETS, "where": r[8]})
    stale = at is None or (now - at).total_seconds() > STALE_MIN * 60
    return {"at": at.isoformat(timespec="seconds") if at else "", "stale": stale, "rows": rows}


def push():
    from sheet_io import write_rows_to_tab
    at = _dt.datetime.now().isoformat(timespec="seconds")
    rows = local_agents()
    write_rows_to_tab(TAB_PREFIX + host(), to_sheet_rows(rows, at))
    print(f"✅ {TAB_PREFIX + host()} に {len(rows)}件 書きました ({at})")
    return 0


def remote(h):
    from sheet_io import read_tab
    return from_sheet_rows(read_tab(TAB_PREFIX + h))


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:                                          # noqa: BLE001
        pass
    cmd = (sys.argv[1:] or ["show"])[0]
    if cmd == "push":
        return push()
    for r in local_agents():
        print(f"{r['state']:5} {r['name']:12} {r['now'][:60]}  {r['url']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
