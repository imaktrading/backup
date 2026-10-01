# -*- coding: utf-8 -*-
"""カタログの「外のサイトを読むだけ」の仕事を KAGOYA で回す (2026-10-01).

依頼: `iMak_data/catalog/requests/2026-10-01_move_heavy_jobs_to_kagoya.md` [IMPLEMENT-GO]
共通ルール: `C:/dev/iMak_data/hq/kagoya_server_rules.md`
ユーザー許可: 2026-10-01 (サーバーへコードと DB の写しを送ることについて)

## 分担 (ルールどおり)

    家   : DB を書く。公式突合の結果 (レポート) を受け取って読む
    鯖   : **読むだけ**。公式サイトを読んで差分を出し、テキストを返す

★移せるのは **DB を書かない仕事** だけ。取り込み (scrapers/*) は DB を書くので家に残す。
  ここで回す4本は、実測で `UPDATE/INSERT/DELETE/upsert(` を1つも持っていない。
★**鍵は送らない** (スプシ・eBay の鍵は要らない仕事だけを選んでいる)。

## 使い方

    python tools/kagoya_catalog.py send                 コードと DB の写しを送る
    python tools/kagoya_catalog.py cycle                結果を取る → 送る → 回す
    python tools/kagoya_catalog.py cycle --jobs drift_bandai
    python tools/kagoya_catalog.py status
    python tools/kagoya_catalog.py run <job>            ★サーバー側で動く入口

結果は `C:/dev/iMak_data/catalog/_kagoya/<job>.out` に入る。
**1本ずつ・1本落ちても後ろを止めない。** 席が取れなければ何もしないで終わる (次の回に続きから)。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # …/iMakCatalog
CFG = Path("C:/dev/iMak_data/hq/offload.json")         # 接続先 (HQ と同じものを読むだけ)
LOCAL_DB = Path("C:/dev/iMak_data/catalog/products.sqlite")
LOCAL_OUT = Path("C:/dev/iMak_data/catalog/_kagoya")
STATE = Path("C:/dev/iMak_data/catalog/_kagoya_state.json")

REMOTE_ROOT = r"C:\setup\CATALOG_offload"
REMOTE_PY = r"C:\Program Files\Python311\python.exe"
REMOTE_CODE = r"C:\dev\iMak\iMakCatalog"
REMOTE_DB = r"C:\dev\iMak_data\catalog\products.sqlite"
SEAT_DIR = r"C:\setup\seats"
OWNER = "CATALOG"
NEED_GB = 0.2          # Chrome を使わない仕事 (共通ルールの目安)
RESERVE_GB = 0.4

# ★突合の「どこまで見たか」の控え。サーバーで進んだ分を家に持ち帰らないと、
#   家の検収が古い控えを見て「差分が残っている」と出し続ける (2026-10-01)
STATE_FILES = {
    # ★ポケモンの --all は控えを書かない作り (全弾まとめて見るので持ち越す物が無い)
    "drift_pokemon": [],
    "drift_opcg": ["_official_drift_state.json"],
    "drift_bandai": ["_official_drift_bandai_state.json"],
    "drift_uniqlo": [],
}

# 読むだけの仕事 (DB を書かないことを 2026-10-01 に実測で確かめた)
JOBS = {
    "drift_pokemon": ["tools/official_drift_pokemon.py", "--all"],
    "drift_opcg": ["tools/official_drift_check.py", "--n", "200"],
    "drift_bandai": ["tools/official_drift_bandai.py"],
    "drift_uniqlo": ["tools/official_drift_uniqlo.py"],
}

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


# ---------------- サーバー側 ----------------

def _free_gb() -> float:
    out = subprocess.run(["powershell", "-NoProfile", "-Command",
                          "(Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory"],
                         capture_output=True, text=True, timeout=60).stdout.strip()
    try:
        return int(out) / (1024 * 1024)
    except ValueError:
        return 0.0


def _pid_alive(pid: int) -> bool:
    import ctypes
    h = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))
    if not h:
        return False
    ctypes.windll.kernel32.CloseHandle(h)
    return True


def take_seat() -> bool:
    """席を取る (共通ルール: 空きメモリ − need_gb ≥ 0.4GB の時だけ)."""
    os.makedirs(SEAT_DIR, exist_ok=True)
    p = Path(SEAT_DIR) / (OWNER + ".json")
    if p.exists():
        try:
            cur = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            cur = {}
        if cur.get("pid") and _pid_alive(cur["pid"]):
            print("[席] 同じ担当の席が生きている → 今は始めない")
            return False
        p.unlink(missing_ok=True)
    # ★HQ が待っている時は譲る (共通ルール 優先順 2)
    if (Path(SEAT_DIR) / "HQ.wait").exists():
        print("[席] HQ が待っている → 譲る")
        return False
    fg = _free_gb()
    if fg - NEED_GB < RESERVE_GB:
        print("[席] 空きメモリ %.2fGB → 今は始めない" % fg)
        return False
    try:
        fd = os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"owner": OWNER, "pid": os.getpid(), "need_gb": NEED_GB,
                   "started": datetime.now().isoformat(timespec="seconds")}, f)
    return True


def free_seat() -> None:
    p = Path(SEAT_DIR) / (OWNER + ".json")
    try:
        if json.loads(p.read_text(encoding="utf-8")).get("pid") == os.getpid():
            p.unlink(missing_ok=True)
    except (OSError, ValueError):
        pass


def server_run(job: str) -> int:
    """サーバー側: 1本だけ回して、結果をファイルに書く."""
    if job not in JOBS:
        print("知らない仕事:", job)
        return 2
    os.makedirs(REMOTE_ROOT, exist_ok=True)
    out = Path(REMOTE_ROOT) / (job + ".out")
    if not take_seat():
        return 3
    t0 = time.time()
    try:
        r = subprocess.run([REMOTE_PY] + JOBS[job], cwd=REMOTE_CODE, capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=6 * 3600)
        body, rc = (r.stdout or "") + (r.stderr or ""), r.returncode
    except Exception as e:
        body, rc = "%s: %s" % (type(e).__name__, e), -1
    finally:
        free_seat()
    sec = int(time.time() - t0)
    head = "=== %s %s (%d秒) rc=%s ===\n" % (
        job, datetime.now().strftime("%Y-%m-%d %H:%M"), sec, rc)
    out.write_text(head + body, encoding="utf-8")
    (Path(REMOTE_ROOT) / (job + ".done.json")).write_text(json.dumps(
        {"job": job, "sec": sec, "rc": rc,
         "at": datetime.now().isoformat(timespec="seconds")}, ensure_ascii=False),
        encoding="utf-8")
    print("%s 終わり %d秒 rc=%s" % (job, sec, rc))
    return 0


# ---------------- 家 側 ----------------

def cfg() -> dict:
    return json.loads(CFG.read_text(encoding="utf-8"))


def _ssh(ps: str, timeout: int = 300):
    c = cfg()
    r = subprocess.run(["ssh", "-i", c["key"], "-o", "BatchMode=yes", "-o", "ConnectTimeout=20",
                        "-o", "LogLevel=ERROR", c["user"] + "@" + c["host"], ps],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=timeout)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def _scp_to(local: str, remote: str, timeout: int = 1800) -> int:
    c = cfg()
    dest = c["user"] + "@" + c["host"] + ":" + remote.replace(chr(92), "/")
    return subprocess.run(
        ["scp", "-q", "-i", c["key"], "-o", "BatchMode=yes", "-o", "LogLevel=ERROR", local, dest],
        capture_output=True, text=True, timeout=timeout).returncode


def _scp_from(remote: str, local: str, timeout: int = 600) -> int:
    c = cfg()
    src = c["user"] + "@" + c["host"] + ":" + remote.replace(chr(92), "/")
    return subprocess.run(
        ["scp", "-q", "-i", c["key"], "-o", "BatchMode=yes", "-o", "LogLevel=ERROR", src, local],
        capture_output=True, text=True, timeout=timeout).returncode


def send(with_db: bool = True) -> bool:
    """コード (py/yaml だけ) と DB の写しを送る."""
    with tempfile.TemporaryDirectory() as tmp:
        tgz = os.path.join(tmp, "catalog.tgz")
        with tarfile.open(tgz, "w:gz") as t:
            for sub in ("tools", "ebay_filter_map", "integrations", "scrapers"):
                d = ROOT / sub
                if not d.exists():
                    continue
                for p in d.rglob("*"):
                    if p.is_file() and p.suffix in (".py", ".yaml", ".yml"):
                        arc = "iMakCatalog/" + str(p.relative_to(ROOT)).replace(chr(92), "/")
                        t.add(p, arcname=arc)
            for name in ("api.py", "__init__.py", "clone_rows.py"):
                if (ROOT / name).exists():
                    t.add(ROOT / name, arcname="iMakCatalog/" + name)
        print("コードを送る (%dKB)" % (os.path.getsize(tgz) // 1024))
        rc, out = _ssh('New-Item -ItemType Directory -Force "%s","C:\\dev\\iMak" | Out-Null; "ok"'
                       % REMOTE_ROOT)
        if rc != 0:
            print("✗ つながらない:", out[:200])
            return False
        if _scp_to(tgz, REMOTE_ROOT + r"\catalog.tgz") != 0:
            print("✗ コードを送れなかった")
            return False
        rc, out = _ssh('cd C:\\dev\\iMak; tar -xzf "%s\\catalog.tgz"; "ok"' % REMOTE_ROOT)
        if rc != 0:
            print("✗ 展開できなかった:", out[:200])
            return False
    if with_db:
        # ★WAL の未反映分を先に畳む (file コピーで控えを取る時の決まり)
        c = sqlite3.connect(str(LOCAL_DB), timeout=120)
        c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        c.close()
        with tempfile.TemporaryDirectory() as tmp:
            copy = os.path.join(tmp, "products.sqlite")
            shutil.copy2(LOCAL_DB, copy)
            print("DB の写しを送る (%dMB)" % (os.path.getsize(copy) // 2 ** 20))
            if _scp_to(copy, REMOTE_ROOT + r"\products.sqlite", timeout=3600) != 0:
                print("✗ DB を送れなかった")
                return False
        _ssh('New-Item -ItemType Directory -Force "C:\\dev\\iMak_data\\catalog" | Out-Null; '
             'Copy-Item "%s\\products.sqlite" "%s" -Force; "ok"' % (REMOTE_ROOT, REMOTE_DB), 600)
    return True


def start(job: str, wait: bool = True) -> bool:
    """1本 回す。既定は **終わるまで待つ**.

    ★`Start-Process -WindowStyle Hidden` で投げっぱなしにすると、走らずに終わることが
      あった (2026-10-01 実測: 4本投げて結果ファイルが1つも出なかった)。
      待つ形なら結果が確かに返るので、既定を待つ方にした。
    """
    if wait:
        rc, out = _ssh('& "%s" "%s\\tools\\kagoya_catalog.py" run %s'
                       % (REMOTE_PY, REMOTE_CODE, job), 6 * 3600 + 60)
        last = (out.strip().splitlines() or ["(出力なし)"])[-1]
        print("  %s: %s" % (job, last))
        return rc == 0
    ps = ('Start-Process -WindowStyle Hidden -FilePath "%s" '
          '-ArgumentList "%s\\tools\\kagoya_catalog.py","run","%s"; "started"'
          % (REMOTE_PY, REMOTE_CODE, job))
    rc, out = _ssh(ps)
    print("  %s: %s" % (job, "投げた" if rc == 0 else "✗ " + out[:120]))
    return rc == 0


def collect(job: str) -> bool:
    LOCAL_OUT.mkdir(parents=True, exist_ok=True)
    if _scp_from(REMOTE_ROOT + "\\" + job + ".out", str(LOCAL_OUT / (job + ".out"))) != 0:
        return False
    _scp_from(REMOTE_ROOT + "\\" + job + ".done.json", str(LOCAL_OUT / (job + ".done.json")))
    # 控え (どこまで見たか) も家に戻す
    for name in STATE_FILES.get(job, []):
        rc = _scp_from("C:/dev/iMak_data/catalog/" + name,
                       "C:/dev/iMak_data/catalog/" + name)
        print("    控え %s %s" % (name, "戻した" if rc == 0 else "戻せなかった"))
    return True


def status() -> None:
    rc, out = _ssh('Get-ChildItem "%s" -ErrorAction SilentlyContinue | '
                   'Select-Object Name,Length,LastWriteTime | Format-Table -AutoSize | Out-String; '
                   '"--- 席 ---"; Get-ChildItem "%s" -ErrorAction SilentlyContinue | '
                   'Select-Object Name | Format-Table -AutoSize | Out-String; '
                   '"空きメモリ MB = " + '
                   '[int]((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory/1KB)'
                   % (REMOTE_ROOT, SEAT_DIR))
    print(out.strip() or ("(つながらない rc=%s)" % rc))


def cycle(jobs, skip_send: bool = False, detach: bool = False) -> int:
    LOCAL_OUT.mkdir(parents=True, exist_ok=True)
    got = 0
    for job in jobs:                       # 先に前回の結果を取る
        if collect(job):
            got += 1
    if got:
        print("前回の結果 %d本 を取り込んだ → %s" % (got, LOCAL_OUT))
    if not skip_send and not send():
        return 1
    for job in jobs:                       # ★1本ずつ。落ちても後ろを止めない
        if start(job, wait=not detach):
            collect(job)                   # 1本ごとに結果を取る (途中で切れても残る)
    STATE.write_text(json.dumps({"last_start": datetime.now().isoformat(timespec="seconds"),
                                 "jobs": list(jobs)}, ensure_ascii=False), encoding="utf-8")
    print("開始した。結果は次の cycle で取り込む (status で様子が見える)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["send", "cycle", "status", "run", "collect"])
    ap.add_argument("job", nargs="?")
    ap.add_argument("--jobs", nargs="*", default=list(JOBS))
    ap.add_argument("--skip-send", action="store_true")
    ap.add_argument("--detach", action="store_true",
                    help="終わるのを待たずに投げる (既定は待つ)")
    a = ap.parse_args()
    if a.action == "run":
        return server_run(a.job or "")
    if a.action == "send":
        return 0 if send() else 1
    if a.action == "status":
        status()
        return 0
    if a.action == "collect":
        for j in ([a.job] if a.job else a.jobs):
            print(j, "取り込んだ" if collect(j) else "まだ無い")
        return 0
    return cycle(a.jobs, a.skip_send, a.detach)


if __name__ == "__main__":
    sys.exit(main())
