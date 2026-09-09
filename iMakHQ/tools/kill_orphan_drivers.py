#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""置き去りのブラウザだけを落とす (2026-09-10 ユーザー要望).

> 動きが遅くなるから、常に要らんものは落とす仕組みを入れて欲しい

■ 何を落とすか
**持ち主が居なくなった自動操作用のブラウザ (chrome / chromedriver) だけ**。

落とさないもの:
  - ユーザーが自分で開いている Chrome (自動操作の目印が無いものは触らない)
  - **今 走っている仕事のブラウザ** (監視くんの run_cycle.py / 抽出くんの scraper 等)。
    ★2026-07-28 のユーザー判断: 「他プロセスには触らず、自分の子だけ片付ける」。
      深夜は 01:30 監視くん / 04:30 リバイスくん が動いており、全部殺すと
      取下げの途中で driver が消える (危険側の失敗)。ここでは所有者が生きているかで
      判定するので、走行中の分は残る。

■ 持ち主の判定
自動操作ブラウザの親をたどり、chrome/chromedriver でない最初の先祖 = 持ち主 (python 等)。
その持ち主が居なければ置き去り。**PIDは使い回される**ので「持ち主が子より後に
生まれている」場合も持ち主なしとみなす (別人が同じ番号を持っただけ)。

使い方: python kill_orphan_drivers.py [--dry-run]
"""
from __future__ import annotations

import json
import subprocess
import sys

# 自動操作の目印。ユーザーが普通に開いた Chrome には付かない。
AUTO_MARKERS = ("--headless", "--remote-debugging-port", "--test-type",
                "--enable-automation")
DRIVER_NAMES = ("chromedriver.exe", "geckodriver.exe", "msedgedriver.exe")
BROWSER_NAMES = ("chrome.exe", "msedge.exe")


def is_automation(proc):
    """自動操作用か (純関数)。driver は常に自動。ブラウザは目印がある時だけ。"""
    name = (proc.get("name") or "").lower()
    if name in DRIVER_NAMES:
        return True
    if name not in BROWSER_NAMES:
        return False
    cmd = proc.get("cmd") or ""
    return any(m in cmd for m in AUTO_MARKERS)


def orphan_roots(procs):
    """落としてよい「置き去りの親玉」の PID を返す (純関数, test可)。

    procs: [{pid, ppid, name, cmd, created}] created は数値 (大きいほど後に起動)。
    戻り: PID の list (この PID を木ごと止めれば、ぶら下がる chrome も消える)。
    """
    by_pid = {p["pid"]: p for p in procs}
    out = []
    for p in procs:
        if not is_automation(p):
            continue
        parent = by_pid.get(p.get("ppid"))
        # 親も自動操作ブラウザ = この子は親玉ではない (親を止めれば一緒に消える)
        if parent is not None and is_automation(parent) and _born_before(parent, p):
            continue
        if _owner_missing(p, by_pid):
            out.append(p["pid"])
    return out


def _born_before(parent, child):
    """親が子より先に生まれているか。PID使い回しの取り違えを防ぐ。"""
    pc, cc = parent.get("created"), child.get("created")
    if pc is None or cc is None:
        return True                      # 判らない時は親子とみなす (壊さない側)
    return pc <= cc


def _owner_missing(proc, by_pid):
    """持ち主 (chrome系でない最初の先祖) が居ないか。"""
    parent = by_pid.get(proc.get("ppid"))
    if parent is None:
        return True
    if not _born_before(parent, proc):
        return True                      # 番号の使い回し = 本当の親は既に居ない
    return False


def _snapshot():
    """今のプロセス一覧を取る (Windows は PowerShell の CIM)。取れなければ空。"""
    if sys.platform != "win32":
        return []
    ps = (
        "Get-CimInstance Win32_Process | "
        "Select-Object ProcessId,ParentProcessId,Name,CommandLine,CreationDate | "
        "ForEach-Object { [pscustomobject]@{ pid=$_.ProcessId; ppid=$_.ParentProcessId; "
        "name=$_.Name; cmd=$_.CommandLine; "
        "created= if($_.CreationDate){[int64]($_.CreationDate.ToFileTimeUtc()/10000000)}else{$null} } } | "
        "ConvertTo-Json -Compress -Depth 3"
    )
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                           capture_output=True, timeout=60)
        data = json.loads((r.stdout or b"").decode("utf-8", "replace") or "[]")
        return data if isinstance(data, list) else [data]
    except Exception as e:                                     # noqa: BLE001
        print("  プロセス一覧を取れませんでした (%s) — 何もしません" % type(e).__name__)
        return []


def _kill(pid):
    try:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                       capture_output=True, timeout=30)
        return True
    except Exception:                                          # noqa: BLE001
        return False


def run(dry_run=False, log=print):
    """置き去りを落とす。戻り: 落とした数 (dry-run なら見つけた数)。"""
    procs = _snapshot()
    if not procs:
        return 0
    pids = orphan_roots(procs)
    if not pids:
        log("🧹 置き去りのブラウザはありません (走行中の分は残します)")
        return 0
    if dry_run:
        log("🧹 置き去り %d件 (--dry-run なので落としません): %s" % (len(pids), pids))
        return len(pids)
    n = sum(1 for p in pids if _kill(p))
    log("🧹 置き去りのブラウザ %d件を落としました" % n)
    return n


if __name__ == "__main__":
    run(dry_run="--dry-run" in sys.argv)
