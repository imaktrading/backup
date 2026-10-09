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
    """タブ名に使う PC 名。AGENT_BOARD_HOST があれば優先 (LAPTOP の実名は IMAKTRADING なので、
    向こうはこれで LAPTOP に揃える。2026-09-29 LAPTOP 回答)。"""
    return (os.environ.get("AGENT_BOARD_HOST") or os.environ.get("COMPUTERNAME") or "").upper() or "THIS-PC"


def _claude_exe():
    """タスクから起動すると PATH に ~/.local/bin が無く claude が見つからない (2026-09-29 LAPTOP 回答)。"""
    import shutil
    got = shutil.which("claude")
    if got:
        return got
    p = os.path.expanduser("~/.local/bin/claude.exe")
    return p if os.path.isfile(p) else "claude"


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
        r = subprocess.run([_claude_exe(), "agents", "--json"], capture_output=True, text=True,
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
                     "url": s["url"], "act": s["act"], "cwd": w.get("cwd") or "",
                     "where": os.path.basename((w.get("cwd") or "").rstrip("\\/"))})
    rows = merge_roster(rows, read_roster())
    order = {"ask": 0, "busy": 1, "idle": 2, "off": 3}
    rows.sort(key=lambda r: (order.get(r["state"], 4), r["name"]))
    return rows


# ------------------------------------------------------------------ 閉じている担当を起動する (2026-09-29)
# 担当の一覧 = デスクトップのフォルダ「Claude」のショートカット (ユーザーが普段ダブルクリックする物)。
# 起動もそのショートカットを開くだけ = 手で押すのと同じ (claude_rc.cmd・版・窓の色がそのまま効く)。

_ROSTER = {"at": 0.0, "rows": []}
# ★2026-10-05: KAGOYA は担当をデスクトップ直下の .bat (例 Catalog.bat) で開いている。.bat も担当として読む
_ROSTER_PS = (
    "[Console]::OutputEncoding = [Text.Encoding]::UTF8;"
    "$desk = [Environment]::GetFolderPath('Desktop'); $d = Join-Path $desk 'Claude';"
    "$ws = New-Object -ComObject WScript.Shell;"
    "@(@(Get-ChildItem $d -Filter *.lnk -ErrorAction SilentlyContinue | ForEach-Object {"
    " $s = $ws.CreateShortcut($_.FullName);"
    " [pscustomobject]@{label=$_.BaseName; args=$s.Arguments; lnk=$_.FullName; text=''} }) +"
    " @(Get-ChildItem $desk -Filter *.bat -ErrorAction SilentlyContinue | ForEach-Object {"
    " [pscustomobject]@{label=$_.BaseName; args=''; lnk=$_.FullName; text=[IO.File]::ReadAllText($_.FullName)} }))"
    " | ConvertTo-Json -Compress")
BAT_LABELS = {"CATALOG": "カタログ"}       # .bat の担当の画面の名前 (無ければ key のまま)
REMOTE_LAUNCH_HOSTS = ("KAGOYA",)        # ssh で一覧を読み・起動できる PC


def _norm(p):
    return str(p or "").replace("/", "\\").rstrip("\\").lower()


def parse_shortcut(label, args, lnk):
    """ショートカット1本 → {key, label, folder, lnk}。claude_rc.cmd を呼ばない物は None (純関数)。"""
    toks = str(args or "").split()
    for i, t in enumerate(toks):
        if t.lower().endswith("claude_rc.cmd") and i + 2 < len(toks):
            name = label[len("Claude "):] if label.startswith("Claude ") else label
            return {"key": toks[i + 2], "label": name, "folder": toks[i + 1].strip('"'), "lnk": lnk}
    return None


def parse_bat(label, text, path):
    """デスクトップの .bat 1本 → {key, label, folder, lnk}。claude を --remote-control で開かない物は None (純関数)。"""
    import re
    if isinstance(text, dict):           # PowerShell 5.1 の Get-Content は {"value": ...} で JSON になる
        text = text.get("value")
    t = str(text or "")
    k = re.search(r"--remote-control\s+([A-Za-z0-9_-]+)", t)
    f = re.search(r'(?im)^\s*cd\s+(?:/d\s+)?"?([^"\r\n]+?)"?\s*$', t)
    if not k or not f:
        return None
    key = k.group(1)
    return {"key": key, "label": BAT_LABELS.get(key, label or key), "folder": f.group(1).strip(), "lnk": path}


def read_roster(ttl=600):
    """担当の一覧 (I/O・10分とっておく)。読めなければ []。"""
    import time
    if _ROSTER["rows"] and time.time() - _ROSTER["at"] < ttl:
        return _ROSTER["rows"]
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", _ROSTER_PS], capture_output=True,
                           text=True, encoding="utf-8", errors="ignore", timeout=20,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        got = json.loads(r.stdout or "[]")
        got = got if isinstance(got, list) else [got]
        rows = [x for x in ((parse_bat(g.get("label", ""), g.get("text", ""), g.get("lnk", ""))
                             if str(g.get("lnk", "")).lower().endswith(".bat")
                             else parse_shortcut(g.get("label", ""), g.get("args", ""), g.get("lnk", "")))
                            for g in got if g) if x]
    except Exception:                                          # noqa: BLE001 読めなければ起動ボタンを出さない
        rows = []
    _ROSTER.update(at=time.time(), rows=rows)
    return rows


def merge_roster(rows, roster):
    """開いている窓に担当の key を付け、開いていない担当を「閉じている」行として足す (純関数)。"""
    by_folder = {_norm(r["folder"]): r for r in roster}
    seen = set()
    out = []
    for r in rows:
        hit = by_folder.get(_norm(r.get("cwd")))
        r = dict(r, key=hit["key"] if hit else "")
        if hit:
            seen.add(hit["key"])
        out.append(r)
    for r in roster:
        if r["key"] not in seen:
            out.append({"name": r["label"], "state": "off", "now": "", "since": "", "started": "",
                        "url": "", "act": [], "cwd": r["folder"], "key": r["key"],
                        "where": os.path.basename(r["folder"].rstrip("\\/"))})
    return out


def _rc_running(folder, lnk=""):
    """この担当の起動用の窓 (cmd の claude_rc.cmd <folder> / .bat) が動いているか。調べられなければ True (起動しない側に倒す)。"""
    ps = ("[Console]::OutputEncoding = [Text.Encoding]::UTF8;"
          "@(Get-CimInstance Win32_Process -Filter \"Name='cmd.exe'\" | ForEach-Object { $_.CommandLine }) | ConvertTo-Json -Compress")
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True,
                           encoding="utf-8", errors="ignore", timeout=20,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        lines = json.loads(r.stdout or "[]")
        lines = lines if isinstance(lines, list) else [lines]
    except Exception:                                          # noqa: BLE001
        return True
    return rc_in_cmdlines(folder, lines, lnk)


def rc_in_cmdlines(folder, cmdlines, lnk=""):
    """cmd のコマンド行の中に、この担当の claude_rc.cmd 起動 (または担当の .bat) があるか (純関数)。"""
    f = _norm(folder)
    bat = _norm(lnk) if str(lnk).lower().endswith(".bat") else ""
    for c in cmdlines or []:
        low = str(c or "").replace("/", "\\").lower()
        if "claude_rc.cmd" in low and (f + " ") in (low + " "):
            return True
        if bat and bat in low:
            return True
    return False


def open_on_desktop(path, key):
    """担当の .lnk / .bat を、画面のある席で開く。

    - 画面の前から (神風のサーバー): エクスプローラーに開かせる = ダブルクリックと同じ
    - ssh から (KAGOYA を家から起動する時): ssh の席には画面が無いので、予約タスク (/it = ログオン中の
      ユーザーの画面で動く) を作って走らせる。2026-10-05 KAGOYA で試験: RDP の席 (session 3) で開いた
    """
    if os.environ.get("SSH_CONNECTION") or os.environ.get("SSH_CLIENT"):
        tn = "iMak_Claude_" + key
        user = os.environ.get("USERNAME") or "Administrator"
        subprocess.run(["schtasks", "/create", "/tn", tn, "/tr", '"%s"' % path, "/sc", "once", "/st", "23:59",
                        "/sd", "2030/01/01", "/it", "/ru", user, "/f"], capture_output=True, timeout=30)
        r = subprocess.run(["schtasks", "/run", "/tn", tn], capture_output=True, timeout=30)
        if r.returncode != 0:
            raise RuntimeError("予約タスクで開けませんでした (rc=%s)" % r.returncode)
        return
    # ★os.startfile だと Console サーバーの環境 (Claude から再起動した時は CLAUDE_CODE_CHILD_SESSION 等) を
    #   そのまま引き継ぎ、開いた担当が「子の会話」扱いで会話を保存しなくなった (2026-09-29 ADV)。
    #   エクスプローラーに開かせる = デスクトップでダブルクリックしたのと同じ環境になる
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith(("CLAUDE", "ANTHROPIC"))}
    subprocess.Popen(["explorer.exe", path], env=env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def launch(key):
    """担当 key のショートカットを開く。既に開いていれば開かない。戻り: (ok, 文)。"""
    hit = [r for r in read_roster() if r["key"] == key]
    if not hit:
        return False, "その担当のショートカットが見つかりません (デスクトップのフォルダ「Claude」)"
    running = {_norm(w.get("cwd")) for w in list_windows()}
    # ★起動して20〜30秒は claude agents に出てこない → その間に2回押すと2つ開いた (2026-09-29 試験で実際に起きた)。
    #   起動用の窓 (claude_rc.cmd <folder>) が居るかも見る
    if _norm(hit[0]["folder"]) in running or _rc_running(hit[0]["folder"], hit[0]["lnk"]):
        return False, "%s はもう開いています (起動中を含む)" % hit[0]["label"]
    open_on_desktop(hit[0]["lnk"], key)
    return True, "%s を起動しました" % hit[0]["label"]


# ------------------------------------------------------------------ 用の済んだ担当を閉じる (2026-10-09 ユーザー)
# ユーザー「各担当が残務がなくなり、待機になったら、CMD 閉じてくれないかな」。
# 閉じる = 起動用の cmd (claude_rc.cmd <folder> / 担当の .bat) を子ごと落とす。依頼が来たら wake でまた開く。
KEEP_OPEN = ("HQ", "ADV", "ALPHA", "BRAVO", "RELAY")   # 窓口と HQ はユーザーが直接話す / RELAY は KAGOYA の呼び鈴の中継なので閉じない
IDLE_MIN = 5                                   # 返事を書き終えてすぐは閉じない (続けて呼び鈴が来ることがある)
LEDGER_TO_KEY = {"カタログ": "CATALOG", "重複くん": "DEDUPE", "監視くん": "INVENTORY",
                 "抽出くん": "HARVEST", "リバイス": "REVISE", "HQ": "HQ"}


def idle_enough(row, now=None, minutes=IDLE_MIN):
    """待機中で、最後の動きから minutes 分たっているか (純関数)。"""
    if not row or row.get("state") != "idle":
        return False
    now = now or _dt.datetime.now()
    try:
        since = _dt.datetime.fromisoformat(row.get("since") or "")
    except ValueError:
        return False
    return (now - since).total_seconds() >= minutes * 60


def open_keys_in_ledger(cur):
    """台帳で担当がまだ持っている依頼 (返した・閉じた 以外) の宛先 key の集合 (純関数)。"""
    return {LEDGER_TO_KEY.get(r.get("to")) for r in cur.values()
            if r.get("state") not in ("返した", "閉じた")} - {None}


def _cmd_pids(folder, lnk=""):
    """この担当の起動用 cmd の PID 一覧。調べられなければ []。"""
    ps = ("[Console]::OutputEncoding = [Text.Encoding]::UTF8;"
          "@(Get-CimInstance Win32_Process -Filter \"Name='cmd.exe'\" | Select-Object ProcessId,CommandLine)"
          " | ConvertTo-Json -Compress")
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True,
                           encoding="utf-8", errors="ignore", timeout=20,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        got = json.loads(r.stdout or "[]")
        got = got if isinstance(got, list) else [got]
    except Exception:                                          # noqa: BLE001
        return []
    return [g["ProcessId"] for g in got if g and rc_in_cmdlines(folder, [g.get("CommandLine")], lnk)]


def close_window(key, force=False):
    """担当 key の窓を閉じる。待機中で IDLE_MIN 分動いていない時だけ (force で省く)。戻り: (ok, 文)。"""
    if key in KEEP_OPEN:
        return False, "%s は閉じない (窓口・HQ)" % key
    hit = [r for r in read_roster() if r["key"] == key]
    if not hit:
        return False, "その担当のショートカットが見つかりません: %s" % key
    row = next((r for r in local_agents() if r.get("key") == key and r["state"] != "off"), None)
    if row and not force and not idle_enough(row):
        return False, "%s は作業中か、動いて %d 分たっていないので閉じない" % (key, IDLE_MIN)
    pids = _cmd_pids(hit[0]["folder"], hit[0]["lnk"])
    if not pids:
        return False, "%s の起動用の窓が見つかりません (閉じている)" % key
    for pid in pids:
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True, timeout=30,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    _close_terminal_window(key + "-web")
    return True, "%s を閉じました" % key


# ★2026-10-09 ユーザー「CMD の窓自体を閉じて」: 家の担当は Windows Terminal の窓 (題 "<KEY>-web") で開く。
#   中を落としても終了コードが0でないと「プロセスは終了しました」の窓が残る → 窓にも閉じる合図を送る
#   (settings.json の defaults に closeOnExit=always も入れた。こちらは設定が戻された時の保険)
_WT_CLOSE_PS = r'''
Add-Type @"
using System;using System.Text;using System.Runtime.InteropServices;
public class WtClose{public delegate bool P(IntPtr h,IntPtr l);
[DllImport("user32.dll")]public static extern bool EnumWindows(P p,IntPtr l);
[DllImport("user32.dll")]public static extern int GetClassName(IntPtr h,StringBuilder s,int n);
[DllImport("user32.dll")]public static extern int GetWindowText(IntPtr h,StringBuilder s,int n);
[DllImport("user32.dll")]public static extern bool PostMessage(IntPtr h,uint m,IntPtr w,IntPtr l);}
"@
[WtClose]::EnumWindows({param($h,$l) $c=New-Object Text.StringBuilder 256;[WtClose]::GetClassName($h,$c,256)|Out-Null;
 if($c.ToString() -eq 'CASCADIA_HOSTING_WINDOW_CLASS'){$t=New-Object Text.StringBuilder 256;[WtClose]::GetWindowText($h,$t,256)|Out-Null;
 if($t.ToString() -eq '__TITLE__'){[WtClose]::PostMessage($h,0x10,[IntPtr]::Zero,[IntPtr]::Zero)|Out-Null}};$true},[IntPtr]::Zero)|Out-Null
'''


def _close_terminal_window(title):
    """題が title のターミナルの窓に閉じる合図 (WM_CLOSE) を送る。無ければ何もしない。"""
    import time
    time.sleep(2)                        # 中が落ちて窓が「終了しました」になるのを待つ
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", _WT_CLOSE_PS.replace("__TITLE__", title)],
                       capture_output=True, timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception:                                          # noqa: BLE001 閉じられなくても中は落ちている
        pass


def sleep_idle():
    """台帳に持ち物が無く、待機中の担当を全部閉じる (家 + KAGOYA)。走行ログ用に1行ずつ返す。"""
    import bravo_ledger as B
    busy_keys = open_keys_in_ledger(B.fold(B.load()))
    out, closed, looked = [], 0, 0
    for r in local_agents():
        k = r.get("key")
        if not k or k in KEEP_OPEN or r["state"] == "off":
            continue
        looked += 1
        if k in busy_keys:
            out.append("%s: 台帳に持ち物あり → 閉じない" % k)
            continue
        ok, msg = close_window(k)
        closed += ok
        out.append(msg)
    for h in REMOTE_LAUNCH_HOSTS:
        try:
            rows = remote_ssh(h)["rows"]
        except Exception as e:                                 # noqa: BLE001
            out.append("%s: 一覧を読めない (%s)" % (h, str(e)[:60]))
            continue
        for r in rows:
            k = r.get("key")
            if not k or k in KEEP_OPEN or r.get("state") == "off":
                continue
            looked += 1
            if k in busy_keys:
                out.append("%s(%s): 台帳に持ち物あり → 閉じない" % (k, h))
                continue
            got = parse_json_out(_remote_py("close " + k, timeout=90)) or {}
            closed += bool(got.get("ok"))
            out.append("%s(%s): %s" % (k, h, got.get("message") or "返事なし"))
    out.append("🛏 待機中の担当を閉じた: %d / 開いていた %d (窓口・HQ は除く)" % (closed, looked))
    return out


# ------------------------------------------------------------------ ssh で届く PC (KAGOYA) — 2026-10-05
# 向こうでこのファイルを動かして一覧を JSON で受け取る / 起動させる。kagoya_offload の ssh を使う

REMOTE_TOOLS = r"C:\dev\iMak\iMakHQ\tools"


def _remote_py(args, timeout=60):
    import kagoya_offload as K
    rc, out = K._ssh(K._cfg(), "python -X utf8 %s\\agent_board.py %s" % (REMOTE_TOOLS, args), timeout=timeout)
    if rc != 0:
        raise RuntimeError((out or "ssh に失敗")[-200:])
    return out


def parse_json_out(out):
    """ssh の出力から最後の JSON 行を取り出す (純関数)。無ければ None。"""
    for ln in reversed(str(out or "").splitlines()):
        ln = ln.strip()
        if ln.startswith(("{", "[")):
            try:
                return json.loads(ln)
            except ValueError:
                continue
    return None


def remote_ssh(h):
    """ssh で届く PC の一覧 → {at, stale, rows}。"""
    rows = parse_json_out(_remote_py("json"))
    if not isinstance(rows, list):
        raise RuntimeError("一覧を読めませんでした")
    return {"at": _dt.datetime.now().isoformat(timespec="seconds"), "stale": False, "rows": rows, "launch": True}


def launch_remote(h, key):
    got = parse_json_out(_remote_py("launch " + key, timeout=90)) or {}
    return bool(got.get("ok")), got.get("message") or "%s で起動できませんでした" % h


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
    if cmd == "json":                    # ssh で読む側 (家の神風) に一覧を返す。ASCII にして文字化けを避ける
        print(json.dumps(local_agents(), ensure_ascii=True))
        return 0
    if cmd == "launch":                  # 家の神風から ssh で起動させる
        ok, msg = launch((sys.argv[2:] or [""])[0])
        print(json.dumps({"ok": ok, "message": msg}, ensure_ascii=True))
        return 0
    if cmd == "close":                   # 担当1つを閉じる (KAGOYA へは ssh で家から呼ばれる)
        ok, msg = close_window((sys.argv[2:] or [""])[0], force="--force" in sys.argv)
        print(json.dumps({"ok": ok, "message": msg}, ensure_ascii=True) if os.environ.get("SSH_CONNECTION")
              else msg)
        return 0
    if cmd == "sleep-idle":              # ブラボーが依頼を閉じた区切りで回す
        for ln in sleep_idle():
            print(ln)
        return 0
    if cmd == "wake":
        # ★2026-09-29 ユーザー「依頼しているわけだから、すぐに処理してもらった方がいい」:
        #   依頼を置いた相手が閉じていたら起動し、一覧に出るまで待つ (その後 SendMessage で呼び鈴)
        #   使い方: python agent_board.py wake CATALOG   (key はデスクトップ「Claude」の担当名。一覧は show)
        import time
        key = (sys.argv[2:] or [""])[0]
        roster = {r["key"]: r for r in read_roster()}
        if key not in roster:
            print(f"その担当がありません: {key} (ある物: {', '.join(sorted(roster))})")
            return 1
        running = {_norm(w.get("cwd")) for w in list_windows()}
        if _norm(roster[key]["folder"]) in running:
            print(f"{key} は開いています → そのまま呼び鈴を鳴らしてください")
            return 0
        ok, msg = launch(key)
        print(msg)
        for _ in range(40):                                    # 最大 約2分
            time.sleep(3)
            if _norm(roster[key]["folder"]) in {_norm(w.get("cwd")) for w in list_windows()}:
                print(f"{key} が開きました → 呼び鈴を鳴らしてください (ListAgents に出る名前へ SendMessage)")
                return 0
        print(f"⚠️ {key} が2分たっても一覧に出ません。依頼書は置いてあるので、開いた時に読みます")
        return 1
    for r in local_agents():
        print(f"{r['state']:5} {r['name']:12} {r['now'][:60]}  {r['url']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
