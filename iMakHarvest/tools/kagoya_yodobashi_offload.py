"""kagoya_yodobashi_offload - ヨドバシ収集 + G-SHOCK反映(GshockMerge) を KAGOYA で回す.

2026-10-02 [IMPLEMENT-GO] (`2026-10-02_harvest_move_rest_to_kagoya.md`、ユーザー最優先
「家のPCの作業を最小に」— 10/2 に家PCが2回落ちた・カタログDB破損3回)。

Chrome不使用のHTTP+Sheets APIのみの軽い処理なので、chara/treasure用offloadの
「仕事ファイルを送る→結果を取り込む」構造は使わず、**既存のスクリプトをそのまま
サーバー上でSSH実行するだけ** (スプシ・eBayの鍵もKAGOYAに置かれたため、書込まで
サーバー側で完結できる。家に結果ファイルを戻す必要は無い — 下流のGshockMergeは
yodobashi_gshockタブ(Google Sheets、どこからでも読める)を読むので、同じ
ファイルシステムに居る必要すらない)。

席は chara/treasure と同じ owner="HARVEST" (1担当1席の設計どおり、同時には動かない。
Chrome不使用なので need_gb は軽め=0.2)。

使い方 (家、予約タスクから):
  python tools/kagoya_yodobashi_offload.py cycle
使い方:
  python tools/kagoya_yodobashi_offload.py status
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import subprocess
import sys
import tarfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)  # iMakHarvest/

HQ_OFFLOAD_CONFIG = r"C:/dev/iMak_data/hq/offload.json"
STATE_PATH = r"C:/dev/iMak_data/harvest/kagoya_yodobashi_state.json"
WORK = r"C:/dev/iMak_data/harvest/kagoya_yodobashi_work"

REMOTE_CODE_ROOT = r"C:\dev\iMak_harvest_offload"  # chara/treasure offload と共有
REMOTE_PY = r"C:\Program Files\Python311\python.exe"
REMOTE_LOG = r"C:\setup\harvest_offload\yodobashi_gshock_run.log"

SEAT_DIR = r"C:\setup\seats"
NEED_GB = 0.2  # Chrome不使用 (chara/treasureの1.0より軽い)
MEM_RESERVE_GB = 0.4


def _pid_alive_win(pid):
    try:
        import ctypes  # noqa: PLC0415
        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))
        if not h:
            return False
        code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(h)
        return code.value == 259
    except Exception:  # noqa: BLE001
        return False


def _cfg():
    c = json.load(open(HQ_OFFLOAD_CONFIG, encoding="utf-8"))
    return {"host": c["host"], "user": c["user"], "key": c["key"]}


def _state():
    try:
        return json.load(open(STATE_PATH, encoding="utf-8"))
    except Exception:
        return {}


def _save_state(st):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    tmp = STATE_PATH + ".tmp"
    json.dump(st, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(tmp, STATE_PATH)


def _ssh(cfg, remote_ps, timeout=1200):
    cmd = ["ssh", "-i", cfg["key"], "-o", "BatchMode=yes", "-o", "ConnectTimeout=20",
           "-o", "LogLevel=ERROR", f"{cfg['user']}@{cfg['host']}", remote_ps]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def _scp_to(cfg, local, remote, timeout=1800):
    cmd = ["scp", "-q", "-i", cfg["key"], "-o", "BatchMode=yes", "-o", "LogLevel=ERROR",
           local, f"{cfg['user']}@{cfg['host']}:{remote.replace(chr(92), '/')}"]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).returncode


def _code_files():
    files = [f for f in os.listdir(REPO) if f.endswith(".py")]
    out = list(files)
    scrapers_dir = os.path.join(REPO, "scrapers")
    for f in os.listdir(scrapers_dir):
        if f.endswith(".py"):
            out.append(os.path.join("scrapers", f))
    for f in ("kagoya_chara_offload.py", "kagoya_treasure_offload.py", "kagoya_yodobashi_offload.py"):
        out.append(os.path.join("tools", f))
    return sorted(out)


def _code_hash(files):
    h = hashlib.sha256()
    for f in files:
        h.update(f.encode())
        with open(os.path.join(REPO, f), "rb") as fh:
            h.update(fh.read())
    return h.hexdigest()[:16]


def sync_code(cfg, st):
    os.makedirs(WORK, exist_ok=True)
    rc, out = _ssh(cfg, f'New-Item -ItemType Directory -Force {REMOTE_CODE_ROOT}\\scrapers,'
                        f'C:\\setup\\harvest_offload | Out-Null; "ok"', timeout=60)
    if rc != 0 or "ok" not in out:
        raise RuntimeError(f"サーバーに置き場を作れない: {out[:200]}")
    files = _code_files()
    ch = _code_hash(files)
    if st.get("code_hash") == ch:
        return
    tgz = os.path.join(WORK, "code.tgz")
    with tarfile.open(tgz, "w:gz") as tf:
        for f in files:
            tf.add(os.path.join(REPO, f), arcname=f.replace(os.sep, "/"))
    if _scp_to(cfg, tgz, r"C:\setup\harvest_offload\code.tgz") != 0:
        raise RuntimeError("コードを送れなかった")
    rc, out = _ssh(cfg, f'cd {REMOTE_CODE_ROOT}; tar -xzf C:\\setup\\harvest_offload\\code.tgz; "ok"', timeout=120)
    if rc != 0 or "ok" not in out:
        raise RuntimeError(f"コードの展開に失敗: {out[:200]}")
    st["code_hash"] = ch
    print(f"  📦 コードを送った ({len(files)}本)")


def acquire_seat(cfg, owner="HARVEST", need_gb=NEED_GB) -> bool:
    """席を取れたか確認する (家からSSH1発でサーバー上の判定を完結させる)。

    chara/treasure offload と同じ `seats/<owner>.json` を見る (owner が同じなので
    1担当1席の制約を共有する = Chrome重量級ジョブと同時には動かない)。
    """
    ps = (
        f'$path = "{SEAT_DIR}\\{owner}.json"; '
        '$pidAlive = $false; '
        'if (Test-Path $path) { '
        '  try { $cur = Get-Content $path -Raw | ConvertFrom-Json } catch { $cur = $null } '
        '  if ($cur -and $cur.pid) { '
        '    try { $p = Get-Process -Id $cur.pid -ErrorAction Stop; $pidAlive = $true } catch { $pidAlive = $false } '
        '  } '
        '  if ($pidAlive) { Write-Output "busy"; exit } '
        '  Remove-Item $path -ErrorAction SilentlyContinue '
        '} '
        f'$m = [math]::Round((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory/1MB,2); '
        f'if ($m - {need_gb} -lt {MEM_RESERVE_GB}) {{ Write-Output "lowmem:$m"; exit }} '
        f'New-Item -ItemType Directory -Force {SEAT_DIR} | Out-Null; '
        f'$body = @{{owner="{owner}"; pid=$PID; need_gb={need_gb}; '
        'started=(Get-Date).ToString("s")} | ConvertTo-Json; '
        '$body | Out-File -FilePath $path -Encoding utf8; '
        '"acquired:$PID"'
    )
    rc, out = _ssh(cfg, ps, timeout=60)
    if rc != 0:
        print(f"  ⚠ 席判定に失敗: {out[:200]}")
        return False
    last = out.strip().splitlines()[-1] if out.strip() else ""
    if last.startswith("acquired"):
        print(f"  🪑 席を取った ({last})")
        return True
    print(f"  ⏸ 席が取れない ({last})")
    return False


def release_seat(cfg, owner="HARVEST"):
    """自分が取った席を消す。 他の処理が既に取り直していた場合は壊さないよう、
    中身を見ずに「あれば消す」ではなく、素直に削除する (このプロセスが呼ぶのは
    acquire直後〜run_remote完了までの間だけなので、取り直されている心配は無い)。"""
    ps = f'Remove-Item "{SEAT_DIR}\\{owner}.json" -ErrorAction SilentlyContinue; "ok"'
    _ssh(cfg, ps, timeout=60)


def run_remote(cfg) -> dict:
    """ヨドバシ収集 → GshockMerge の順でサーバー上で実行し、ログの要点を返す。"""
    cmd = (
        f'cd {REMOTE_CODE_ROOT}; '
        f'& "{REMOTE_PY}" -u run_harvest_yodobashi.py 2>&1 | Tee-Object -FilePath {REMOTE_LOG}; '
        f'& "{REMOTE_PY}" -u run_gshock_merge.py 2>&1 | Tee-Object -FilePath {REMOTE_LOG} -Append; '
        '"EXIT=$LASTEXITCODE"'
    )
    rc, out = _ssh(cfg, cmd, timeout=1800)
    return {"rc": rc, "tail": "\n".join(out.strip().splitlines()[-25:])}


def cycle() -> int:
    cfg = _cfg()
    st = _state()
    today = datetime.date.today().isoformat()
    if st.get("done_date") == today:
        print("✅ 今日の分は済み")
        return 0
    if not acquire_seat(cfg):
        return 0
    try:
        sync_code(cfg, st)
        _save_state(st)
        res = run_remote(cfg)
        print(res["tail"])
        if "EXIT=0" in res["tail"]:
            st["done_date"] = today
            st.pop("last_error", None)
            print("✅ ヨドバシ収集+GshockMerge 完了")
        else:
            st["last_error"] = f"{datetime.datetime.now():%m/%d %H:%M} exit非0"
            print("⚠ 異常終了の可能性 (ログ参照)")
        _save_state(st)
    finally:
        release_seat(cfg)
    return 0


def status():
    print(json.dumps(_state(), ensure_ascii=False, indent=1))


def main():
    a = sys.argv[1:]
    if not a or a[0] == "cycle":
        return cycle()
    if a[0] == "status":
        status()
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
