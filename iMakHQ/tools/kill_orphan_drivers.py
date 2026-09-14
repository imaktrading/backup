#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""置き去りのプロセスだけを落とす (2026-09-10 ユーザー要望 / 2026-09-14 対象を追加).

> 動きが遅くなるから、常に要らんものは落とす仕組みを入れて欲しい

■ 何を落とすか
  1. **持ち主が居なくなった自動操作用のブラウザ** (chrome / chromedriver)
  2. **ディスク全体の検索** (`find / ...`) で STALE_SEARCH_SEC 以上 走っているもの
     ★2026-09-14: Claude の Bash が起動した `find / -iname ...` が 13:51 / 17:15 / 18:46 から
       放置され、CPU 67% の主因だった。ディスク全体を10分以上なめる検索に正当な用途は無い
  3. **持ち主が居なくなったテスト走行** (`python -m pytest`)
     ★2026-09-14: headless セッション (19:10 完了) の `pytest -q` が 4GB で固まって残った

落とさないもの:
  - ユーザーが自分で開いている Chrome (自動操作の目印が無いものは触らない)
  - **今 走っている仕事のブラウザ / テスト** (監視くんの run_cycle.py / pre-commit のテスト等)。
    ★2026-07-28 のユーザー判断: 「他プロセスには触らず、自分の子だけ片付ける」。
      持ち主が生きているかで判定するので、走行中の分は残る。

■ 持ち主の判定
親をたどり、ブラウザ/シェル/python でない最初の先祖 = 持ち主 (claude / git / pythonw の常駐 等)。
その持ち主が居なければ置き去り。**PIDは使い回される**ので「持ち主が子より後に
生まれている」場合も持ち主なしとみなす (別人が同じ番号を持っただけ)。

使い方: python kill_orphan_drivers.py [--dry-run]
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time

# 自動操作の目印。ユーザーが普通に開いた Chrome には付かない。
AUTO_MARKERS = ("--headless", "--remote-debugging-port", "--test-type",
                "--enable-automation")
DRIVER_NAMES = ("chromedriver.exe", "geckodriver.exe", "msedgedriver.exe")
BROWSER_NAMES = ("chrome.exe", "msedge.exe")
# 持ち主を探す時に「中継ぎ」として飛ばすもの (これ自体は持ち主にならない)
RELAY_NAMES = ("bash.exe", "sh.exe", "cmd.exe", "conhost.exe", "powershell.exe",
               "python.exe", "python3.11.exe", "python3.exe")
STALE_SEARCH_SEC = 10 * 60
ORPHAN_TEST_MIN_SEC = 2 * 60     # 終わった直後の片付け中を巻き込まない
_ROOT_FIND = re.compile(r'find(?:\.exe)?"?\s+(?:/|/c/?|[A-Za-z]:[\\/]?)(?:\s|$)', re.I)
# Windows の FILETIME (1601年起点の秒) と UNIX 秒の差
_FILETIME_EPOCH_OFFSET = 11644473600


def is_automation(proc):
    """自動操作用か (純関数)。driver は常に自動。ブラウザは目印がある時だけ。"""
    name = (proc.get("name") or "").lower()
    if name in DRIVER_NAMES:
        return True
    if name not in BROWSER_NAMES:
        return False
    cmd = proc.get("cmd") or ""
    return any(m in cmd for m in AUTO_MARKERS)


def is_root_search(proc):
    """ディスク全体の検索か (純関数)。`find / ...` / `find /c ...` / `find C:\\ ...`。"""
    if (proc.get("name") or "").lower() != "find.exe":
        return False
    return bool(_ROOT_FIND.search(proc.get("cmd") or ""))


def is_test_run(proc):
    """テスト走行か (純関数)。"""
    name = (proc.get("name") or "").lower()
    return name.startswith("python") and "-m pytest" in (proc.get("cmd") or "")


def orphan_roots(procs, now=None):
    """落としてよい「置き去りの親玉」の PID を返す (純関数, test可)。

    procs: [{pid, ppid, name, cmd, created}] created は秒 (大きいほど後に起動)。
    now:   created と同じ単位の現在時刻。None なら時間の条件 (検索/テスト) は判定しない。
    戻り: PID の list (この PID を木ごと止めれば、ぶら下がる子も消える)。
    """
    by_pid = {p["pid"]: p for p in procs}
    out = []
    for p in procs:
        if is_automation(p):
            parent = by_pid.get(p.get("ppid"))
            # 親も自動操作ブラウザ = この子は親玉ではない (親を止めれば一緒に消える)
            if parent is not None and is_automation(parent) and _born_before(parent, p):
                continue
            if _owner_missing(p, by_pid):
                out.append(p["pid"])
        elif is_root_search(p):
            if _age(p, now) is not None and _age(p, now) >= STALE_SEARCH_SEC:
                out.append(p["pid"])
        elif is_test_run(p):
            if (_age(p, now) is not None and _age(p, now) >= ORPHAN_TEST_MIN_SEC
                    and _relay_owner_missing(p, by_pid)):
                out.append(p["pid"])
    return out


def _age(proc, now):
    c = proc.get("created")
    if now is None or c is None:
        return None                      # 判らない = 落とさない側
    return now - c


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


def _relay_owner_missing(proc, by_pid):
    """シェル/python の中継ぎを飛ばした先の持ち主が居ないか。

    pre-commit のテストは git → bash → python と続き、git が生きているので残る。
    headless セッションのテストは claude → bash → bash → python で、claude が消えると置き去り。
    """
    cur = proc
    for _ in range(12):
        parent = by_pid.get(cur.get("ppid"))
        if parent is None or not _born_before(parent, cur):
            return True
        if (parent.get("name") or "").lower() not in RELAY_NAMES:
            return False                 # 持ち主が生きている
        cur = parent
    return False                         # 深すぎて判らない = 落とさない側


def decode_ps_output(raw):
    """PowerShell の出力を文字列にする (純関数)。utf-8 で読めなければ cp932。

    replace で無理に読まない: 置換された2バイト文字が JSON のエスケープを壊す。
    """
    raw = raw or b""
    for enc in ("utf-8-sig", "cp932"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return ""


def _snapshot():
    """今のプロセス一覧を取る (Windows は PowerShell の CIM)。取れなければ空。"""
    if sys.platform != "win32":
        return []
    # ★2026-09-14: 出力を UTF-8 に固定する。既定は cp932 で、日本語のコマンド行
    #   (2バイト目が 0x5C = `\` になる文字) を utf-8 の replace で読むと JSON のエスケープが壊れ、
    #   **毎回「一覧を取れませんでした」で何もしていなかった** (出品くんの定期掃除も含めて)。
    ps = (
        "[Console]::OutputEncoding=[Text.Encoding]::UTF8; "
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
        data = json.loads(decode_ps_output(r.stdout) or "[]")
        return data if isinstance(data, list) else [data]
    except Exception as e:                                     # noqa: BLE001
        print("  プロセス一覧を取れませんでした (%s) — 何もしません" % type(e).__name__)
        return []


_GIT_KILL = r"C:\Program Files\Git\usr\bin\kill.exe"


def _kill(pid):
    """止める。Git Bash 由来のプロセスは taskkill が効かないことがあるので kill -f も試す。"""
    ok = False
    try:
        r = subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                           capture_output=True, timeout=30)
        ok = r.returncode == 0
    except Exception:                                          # noqa: BLE001
        pass
    if not ok and os.path.exists(_GIT_KILL):
        try:
            r = subprocess.run([_GIT_KILL, "-f", str(pid)], capture_output=True, timeout=30)
            ok = r.returncode == 0
        except Exception:                                      # noqa: BLE001
            pass
    return ok


def run(dry_run=False, log=print):
    """置き去りを落とす。戻り: 落とした数 (dry-run なら見つけた数)。"""
    procs = _snapshot()
    if not procs:
        return 0
    now = int(time.time()) + _FILETIME_EPOCH_OFFSET
    pids = orphan_roots(procs, now=now)
    if not pids:
        log("🧹 置き去りはありません (走行中の分は残します)")
        return 0
    by_pid = {p["pid"]: p for p in procs}
    what = ["%s(%s)" % (by_pid[p].get("name"), p) for p in pids]
    if dry_run:
        log("🧹 置き去り %d件 (--dry-run なので落としません): %s" % (len(pids), ", ".join(what)))
        return len(pids)
    n = sum(1 for p in pids if _kill(p))
    log("🧹 置き去り %d件を落としました: %s" % (n, ", ".join(what)))
    return n


LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "review_logs",
                        "kill_stale_procs.log")


def _log_to_file(msg):
    """タスク (pythonw) から走ると print は見えないので、1行ずつ残す = 動いた証拠。"""
    print(msg)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write("[%s] %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg))
    except OSError:
        pass


if __name__ == "__main__":
    run(dry_run="--dry-run" in sys.argv, log=_log_to_file)
