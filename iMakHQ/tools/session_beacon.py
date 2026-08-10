#!/usr/bin/env python3
"""稼働中の Claude セッションを worktree 単位で申告する beacon.

## なぜ要るか (2026-08-10 の実害)

`dispatch_worktree` は `dispatch_<wt>.lock` で **headless 同士**の二重起動を防いでいる。
しかし **人が開いた対話セッション**は lock を取らないので、hub から見ると「誰も居ない」。
その結果 2026-08-10 に catalog worktree で:

    12:09〜  対話 Catalog セッションが依頼2件を処理中
    12:35-37 headless Catalog が同じ item を先に完遂 → 3コミット (803c74a / 6e16270 / 1eef38b)

が起き、**二重作業**と**誤コミット**を誘発した (今回は commit 済で消失なし。ただし
CLAUDE.md「1 worktree 1 branch / 並列消失事故」に抵触。過去3回は実際に消えている)。

## 仕組み

- 全セッションの **SessionStart hook** が `stamp` を呼び、
  `C:/dev/iMak_data/_sessions/<wt>.json` に「誰が居るか」を書く
- hook 自身は即終了するので、**PID は claude.exe の祖先を辿って記録**する
  (hook プロセスの PID を書くと即死して意味が無い)
- 生存判定は PID。セッションが閉じれば claude.exe が消える = 自動的に無効
  → **release を書き忘れて永久ロックになる事故が起きない**
- `C:/dev/iMak` (本元) は **対象外**。窓口4席が意図的に共有しているため
  (Advisor / 出品専任 / ALPHA / BRAVO)

判定不能なら「居ない」に倒す。beacon は dispatch を**止める**方向に効くので、
誤検知で全 worktree が止まる方が害が大きい (2026-07-29 に孤児 lock で3時間 全停止した前例)。
"""
from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

SESSIONS_DIR = Path(r"C:\dev\iMak_data\_sessions")

# worktree ルート → wt 名。**本元 (C:/dev/iMak) は入れない** (4席が共有しているので排他しない)。
ROOT_TO_WT = {
    r"c:/dev/imak_catalog": "catalog",
    r"c:/dev/imak_dedupe": "dedupe",
    r"c:/dev/imak_inventory": "inventory",
    r"c:/dev/imak_harvest": "harvest",
    r"c:/dev/imak_revise": "revise",
}

BEACON_MAX_AGE_SEC = 24 * 3600     # PID が読めない時だけ効く保険


def _norm(p: str) -> str:
    return (p or "").replace("\\", "/").rstrip("/").lower()


def wt_for_path(path: str) -> "str | None":
    """path が属する worktree 名。本元・対象外は None."""
    n = _norm(path)
    for root, wt in ROOT_TO_WT.items():
        if n == root or n.startswith(root + "/"):
            return wt
    return None


# --------------------------------------------------------------- プロセス生存

def pid_alive(pid: int) -> bool:
    """PID が生きているか。**分からない時は False** (= 居ない扱い)。

    ★`os.kill(pid, 0)` は使わない。Windows の CPython では TerminateProcess になり
      「生存確認のつもりで相手を殺す」(dispatch_worktree と同じ理由)。
    """
    if not pid or pid <= 0:
        return False
    if os.name != "nt":
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259
    try:
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not h:
            return False
        try:
            code = ctypes.c_ulong()
            if k32.GetExitCodeProcess(h, ctypes.byref(code)):
                return code.value == STILL_ACTIVE
            return False
        finally:
            k32.CloseHandle(h)
    except Exception:                                    # noqa: BLE001
        return False


class _PROCESSENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", ctypes.c_ulong),
        ("cntUsage", ctypes.c_ulong),
        ("th32ProcessID", ctypes.c_ulong),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID", ctypes.c_ulong),
        ("cntThreads", ctypes.c_ulong),
        ("th32ParentProcessID", ctypes.c_ulong),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", ctypes.c_ulong),
        ("szExeFile", ctypes.c_char * 260),
    ]


def process_table() -> dict:
    """pid -> (親pid, 実行ファイル名) の表。取れなければ空 dict。

    ★`wmic` は使わない。Windows 11 の新しいビルドでは **削除されている**
      (2026-08-10 実測: このマシンに wmic が無く、親を辿れず beacon が機能しなかった)。
      外部プロセスを起こさない Toolhelp32 スナップショットに統一する。
    """
    if os.name != "nt":
        return {}
    TH32CS_SNAPPROCESS = 0x2
    INVALID = ctypes.c_void_p(-1).value
    try:
        k32 = ctypes.windll.kernel32
        snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if not snap or snap == INVALID:
            return {}
        try:
            e = _PROCESSENTRY32()
            e.dwSize = ctypes.sizeof(_PROCESSENTRY32)
            out = {}
            ok = k32.Process32First(snap, ctypes.byref(e))
            while ok:
                out[int(e.th32ProcessID)] = (
                    int(e.th32ParentProcessID),
                    e.szExeFile.decode("ascii", "replace").lower(),
                )
                ok = k32.Process32Next(snap, ctypes.byref(e))
            return out
        finally:
            k32.CloseHandle(snap)
    except Exception:                                    # noqa: BLE001
        return {}


def owning_session_pid(start_pid: "int | None" = None, max_hops: int = 6,
                       table: "dict | None" = None) -> int:
    """claude.exe の祖先を辿ってその PID を返す。見つからなければ直近の親 PID。

    hook プロセス自身の PID を書いても即死するので意味が無い。**セッションの寿命を持つ
    プロセス** (= claude.exe) を記録する。
    """
    tbl = process_table() if table is None else table
    pid = start_pid if start_pid is not None else os.getpid()
    fallback = pid
    for _ in range(max_hops):
        entry = tbl.get(pid)
        if not entry:
            break
        parent, _name = entry
        if not parent or parent == pid or parent not in tbl:
            break
        fallback = parent
        if "claude" in tbl[parent][1]:
            return parent
        pid = parent
    return fallback


# --------------------------------------------------------------- 読み書き

def beacon_path(wt: str) -> Path:
    return SESSIONS_DIR / f"{wt}.json"


def stamp(cwd: "str | None" = None) -> "dict | None":
    """今のセッションを beacon に記録。対象外 worktree なら何もしない (None)."""
    root = _git_root(cwd or os.getcwd())
    wt = wt_for_path(root or (cwd or os.getcwd()))
    if not wt:
        return None                                      # 本元/対象外 = 排他しない
    rec = {
        "wt": wt,
        "pid": owning_session_pid(),
        "root": root,
        "at": datetime.now().isoformat(timespec="seconds"),
    }
    try:
        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        beacon_path(wt).write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        return None
    return rec


def _git_root(cwd: str) -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=cwd,
                             capture_output=True, text=True, timeout=15,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return (out.stdout or "").strip()
    except Exception:                                    # noqa: BLE001
        return ""


def active_session(wt: str, now: "float | None" = None) -> "dict | None":
    """その worktree で **今動いているセッション**。居なければ None。

    - beacon が無い → None
    - PID が生きている → そのセッション
    - PID が死んでいる → None (閉じたセッション。release 不要でここが効く)
    - PID が読めない → 時間で判定 (24h 以内なら居る扱い) = 最後の保険
    """
    import time as _t
    p = beacon_path(wt)
    try:
        rec = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    pid = rec.get("pid")
    if isinstance(pid, int) and pid > 0:
        return rec if pid_alive(pid) else None
    try:
        age = (now or _t.time()) - p.stat().st_mtime
    except OSError:
        return None
    return rec if age < BEACON_MAX_AGE_SEC else None


def clear(wt: str) -> None:
    beacon_path(wt).unlink(missing_ok=True)


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "stamp"
    if cmd == "stamp":
        rec = stamp()
        if rec:
            print(f"session beacon: {rec['wt']} pid={rec['pid']}")
        return 0
    if cmd == "list":
        # ★cp932 コンソールで落ちない文字だけ使う (今朝 同型で expected を落とした)
        for wt in sorted(ROOT_TO_WT.values()):
            a = active_session(wt)
            state = f"稼働中 pid={a['pid']} ({a['at']})" if a else "(居ない)"
            print(f"  {wt:10} {state}")
        return 0
    if cmd == "clear" and len(sys.argv) > 2:
        clear(sys.argv[2])
        return 0
    print("usage: session_beacon.py [stamp|list|clear <wt>]")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
