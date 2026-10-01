"""kagoya_treasure_offload - トレジャーハント収集を KAGOYA サーバーで回す.

2026-10-01 [IMPLEMENT-GO] (`2026-10-01_move_heavy_jobs_to_kagoya.md`)。
`kagoya_chara_offload.py` と同じ形 (家/サーバーの分担・席の取り方は同一)。差分は2つ:
  ① 検索語 = `demand_market.csv` (eBay実売台帳) + カードごとの仕入上限 (card_limits)
  ② 書込先 = 中間スプシの `mercari_psa10_treasure` タブ (末尾に上限判定列)

コード展開先・SEAT_DIR・HQとの関係は kagoya_chara_offload.py と共有 (同じサーバー・
同じ owner="HARVEST")。 仕事ファイルの置き場だけ別サブフォルダにして、 キャラ収集の
job.json/result.json と混ざらないようにする (`C:\\setup\\harvest_offload\\treasure`)。
席は1担当1つなので、 キャラ収集とトレジャーハントは元々同時には動かない。

使い方 (家):
  python tools/kagoya_treasure_offload.py cycle
  python tools/kagoya_treasure_offload.py status
使い方 (サーバー。家の cycle が起動する):
  python tools/kagoya_treasure_offload.py run C:\\setup\\harvest_offload\\treasure\\job.json
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
STATE_PATH = r"C:/dev/iMak_data/harvest/kagoya_treasure_state.json"
WORK = r"C:/dev/iMak_data/harvest/kagoya_treasure_work"

REMOTE_ROOT = r"C:\setup\harvest_offload\treasure"
REMOTE_PY = r"C:\Program Files\Python311\python.exe"
REMOTE_CODE_ROOT = r"C:\dev\iMak_harvest_offload"  # キャラ収集と共有 (同じコード一式)

REMOTE_BUSY_MARKERS = ("kagoya_offload.py",)  # HQの補探索と重ならない (chara版と同じ判定)


# ---------------------------------------------------------------------------
# サーバーの席 (kagoya_chara_offload.py と同じ実装。 担当ごとに置き場が別なのでコピー)
# ---------------------------------------------------------------------------
SEAT_DIR = r"C:\setup\seats"
HARVEST_NEED_GB = 1.2
MEM_RESERVE_GB = 0.4
PAUSE_RESERVE_GB = 0.3
HQ_OFFLOAD_REMOTE_ROOT = r"C:\setup\offload"
HQ_WAIT_PATH = os.path.join(SEAT_DIR, "HQ.wait")
HQ_WAIT_MAX_HOURS = 2.0


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


def free_gb_win() -> float:
    try:
        import ctypes  # noqa: PLC0415

        class MS(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("total", ctypes.c_ulonglong), ("avail", ctypes.c_ulonglong),
                        ("a", ctypes.c_ulonglong), ("b", ctypes.c_ulonglong), ("c", ctypes.c_ulonglong),
                        ("d", ctypes.c_ulonglong), ("e", ctypes.c_ulonglong)]
        m = MS()
        m.dwLength = ctypes.sizeof(m)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        return m.avail / 1024 ** 3
    except Exception:  # noqa: BLE001
        return 0.0


def seat_is_free(seat, pid_alive):
    if not isinstance(seat, dict) or not seat.get("pid"):
        return True
    return not pid_alive(seat["pid"])


def can_take_seat(need_gb, free_gb, reserve_gb=MEM_RESERVE_GB) -> bool:
    return free_gb - need_gb >= reserve_gb


def acquire_server_seat(owner, need_gb=HARVEST_NEED_GB, seat_dir=SEAT_DIR, free_gb=None, pid_alive=None):
    pid_alive = pid_alive or _pid_alive_win
    os.makedirs(seat_dir, exist_ok=True)
    path = os.path.join(seat_dir, owner + ".json")
    if os.path.exists(path):
        try:
            cur = json.load(open(path, encoding="utf-8"))
        except Exception:  # noqa: BLE001
            cur = None
        if not seat_is_free(cur, pid_alive):
            return False
        try:
            os.remove(path)
        except OSError:
            return False
    fg = free_gb_win() if free_gb is None else free_gb
    if not can_take_seat(need_gb, fg):
        print(f"[seat] 空きメモリ {fg:.2f}GB / 要る {need_gb}GB + 余裕 {MEM_RESERVE_GB}GB → 今は始めない",
              flush=True)
        return False
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"owner": owner, "pid": os.getpid(), "need_gb": need_gb,
                   "started": datetime.datetime.now().isoformat(timespec="seconds")}, f)
    return True


def release_server_seat(owner, seat_dir=SEAT_DIR):
    path = os.path.join(seat_dir, owner + ".json")
    try:
        cur = json.load(open(path, encoding="utf-8"))
        if cur.get("pid") == os.getpid():
            os.remove(path)
    except Exception:  # noqa: BLE001
        pass


def _hq_seat_alive() -> bool:
    try:
        seat = json.load(open(os.path.join(SEAT_DIR, "HQ.json"), encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return False
    return not seat_is_free(seat, _pid_alive_win)


def hq_today_done() -> bool:
    try:
        job = json.load(open(os.path.join(HQ_OFFLOAD_REMOTE_ROOT, "job.json"), encoding="utf-8"))
        if job.get("date") != datetime.date.today().isoformat():
            return False
        return os.path.exists(os.path.join(HQ_OFFLOAD_REMOTE_ROOT, "done.json"))
    except Exception:  # noqa: BLE001
        return False


def may_start() -> bool:
    return _hq_seat_alive() or hq_today_done()


def should_pause_now() -> bool:
    if os.path.exists(HQ_WAIT_PATH):
        try:
            since = json.load(open(HQ_WAIT_PATH, encoding="utf-8")).get("since")
            age_h = (datetime.datetime.now() - datetime.datetime.fromisoformat(since)).total_seconds() / 3600
            if age_h <= HQ_WAIT_MAX_HOURS:
                return True
        except Exception:  # noqa: BLE001
            return True
    return free_gb_win() < PAUSE_RESERVE_GB


# ---------------------------------------------------------------------------
# サーバー側
# ---------------------------------------------------------------------------
def run_job(job_path: str) -> None:
    if not may_start():
        print("[run] HQ の今日の分がまだ動いていない/終わっていない → 今回は動かない (次の回に続きから)",
              flush=True)
        return
    if not acquire_server_seat("HARVEST"):
        print("[run] 席が取れない (空きメモリ不足/自分の席が残っている) → 今回は動かない (次の回に続きから)",
              flush=True)
        return
    try:
        _run_job_body(job_path)
    finally:
        release_server_seat("HARVEST")


def _run_job_body(job_path: str) -> None:
    sys.path.insert(0, REMOTE_CODE_ROOT)
    import run_harvest_mercari_psa10 as psa10  # noqa: PLC0415
    from scrapers._chrome_util import kill_chrome_for_profile, kill_orphan_chromedriver  # noqa: PLC0415
    from scrapers import mercari_seller as MS  # noqa: PLC0415

    job = json.load(open(job_path, encoding="utf-8"))
    d = os.path.dirname(job_path)
    dump_path_str = os.path.join(d, "result.json")

    resume = None
    if os.path.exists(dump_path_str):
        try:
            resume = json.loads(open(dump_path_str, encoding="utf-8").read())
            print(f"[run] 前回の続きから再開 (候補 {len(resume.get('candidates') or [])}件)", flush=True)
        except Exception:  # noqa: BLE001
            resume = None

    from pathlib import Path  # noqa: PLC0415
    treasure_args = _server_treasure_args(job)

    kill_chrome_for_profile(MS.CHROME_PROFILE_DIR_ANON)
    kill_orphan_chromedriver()
    try:
        payload = psa10.collect(treasure_args, dump_path=Path(dump_path_str), resume=resume, on_flush=None,
                                should_pause=should_pause_now)
    finally:
        kill_chrome_for_profile(MS.CHROME_PROFILE_DIR_ANON)
        kill_orphan_chromedriver()

    unfinished = bool(payload.get("truncated"))
    print(f"[run] {'区切って終了' if unfinished else '完了'}: 候補 {len(payload['candidates'])}件 / "
          f"番号読めず {len(payload.get('unreadable') or [])}件", flush=True)
    if unfinished:
        return
    json.dump({"finished": datetime.datetime.now().isoformat(timespec="seconds")},
              open(os.path.join(d, "done.json"), "w", encoding="utf-8"))


def _server_treasure_args(job):
    """`no_dedupe=True` でスプシの鍵が要る処理を呼ばない (chara版と同じ考え方)。"""
    import argparse  # noqa: PLC0415

    return argparse.Namespace(
        keywords=job["keywords"], games=None, from_demand=False, demand_only=False, demand_limit=0,
        headless=True, manual=False, price_min=3000, price_max=70000, min_rating=100,
        no_identity=False, cap_per_keyword=100, keyword_interval=8.0, max_details=0,
        no_dedupe=True, save_every=10, sheet_every=10_000_000,
        max_consecutive_errors=3, strict_gates=True,
        cost_cfg={"max_jpy": job["cost_max_jpy"]}, card_limits=job.get("card_limits") or {},
    )


# ---------------------------------------------------------------------------
# 家の側: 送る・起動・取りに行く
# ---------------------------------------------------------------------------
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


def _ssh(cfg, remote_ps, timeout=120):
    cmd = ["ssh", "-i", cfg["key"], "-o", "BatchMode=yes", "-o", "ConnectTimeout=20",
           "-o", "LogLevel=ERROR", f"{cfg['user']}@{cfg['host']}", remote_ps]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def _scp_to(cfg, local, remote, timeout=1800):
    cmd = ["scp", "-q", "-i", cfg["key"], "-o", "BatchMode=yes", "-o", "LogLevel=ERROR",
           local, f"{cfg['user']}@{cfg['host']}:{remote.replace(chr(92), '/')}"]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).returncode


def _scp_from(cfg, remote, local, timeout=600):
    cmd = ["scp", "-q", "-i", cfg["key"], "-o", "BatchMode=yes", "-o", "LogLevel=ERROR",
           f"{cfg['user']}@{cfg['host']}:{remote.replace(chr(92), '/')}", local]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).returncode


def _code_files():
    """同期する .py 一覧 (iMakHarvest 直下 + scrapers/ 配下 + 両offloadスクリプト)。"""
    files = [f for f in os.listdir(REPO) if f.endswith(".py")]
    out = list(files)
    scrapers_dir = os.path.join(REPO, "scrapers")
    for f in os.listdir(scrapers_dir):
        if f.endswith(".py"):
            out.append(os.path.join("scrapers", f))
    out.append(os.path.join("tools", "kagoya_chara_offload.py"))
    out.append(os.path.join("tools", "kagoya_treasure_offload.py"))
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
    rc, out = _ssh(cfg, f'New-Item -ItemType Directory -Force {REMOTE_ROOT},{REMOTE_CODE_ROOT}\\scrapers | '
                        f'Out-Null; "ok"')
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
    if _scp_to(cfg, tgz, REMOTE_ROOT + r"\code.tgz") != 0:
        raise RuntimeError("コードを送れなかった")
    rc, out = _ssh(cfg, f'cd {REMOTE_CODE_ROOT}; tar -xzf {REMOTE_ROOT}\\code.tgz; "ok"')
    if rc != 0 or "ok" not in out:
        raise RuntimeError(f"コードの展開に失敗: {out[:200]}")
    st["code_hash"] = ch
    print(f"  📦 コードを送った ({len(files)}本)")


def build_job(today: str) -> dict:
    sys.path.insert(0, REPO)
    from scrapers import treasure_keywords  # noqa: PLC0415
    import run_harvest_mercari_psa10 as psa10  # noqa: PLC0415
    from sheet_writer_mercari_search import load_keys_all_tabs  # noqa: PLC0415
    from sheet_writer_mercari_seller import open_seller_staging_sheet  # noqa: PLC0415

    rows = treasure_keywords.load_rows()
    keywords = treasure_keywords.build_keywords(rows)
    limits = treasure_keywords.build_cost_limits(rows)
    cost_cfg = psa10.load_cost_sanity()
    known = load_keys_all_tabs(open_seller_staging_sheet())
    return {"job_id": f"treasure-{today}", "keywords": keywords, "card_limits": limits,
            "cost_max_jpy": cost_cfg["max_jpy"], "known_keys": sorted(known)}


def remote_busy(cfg) -> bool:
    conds = " -or ".join(f"$_.CommandLine -like '*{m}*'" for m in REMOTE_BUSY_MARKERS)
    ps = (f'$n = @(Get-CimInstance Win32_Process -Filter "Name=\'python.exe\'" | '
          f'Where-Object {{ {conds} }}).Count; "$n"')
    rc, out = _ssh(cfg, ps)
    if rc != 0:
        return True
    try:
        return int(out.strip().splitlines()[-1]) > 0
    except Exception:  # noqa: BLE001
        return True


def remote_status(cfg) -> dict:
    ps = (f'$d = Test-Path {REMOTE_ROOT}\\done.json; '
          f'$p = @(Get-CimInstance Win32_Process -Filter "Name=\'python.exe\'" | '
          f'Where-Object {{ $_.CommandLine -like \'*kagoya_treasure_offload.py*run*\' }}).Count; "$d|$p"')
    rc, out = _ssh(cfg, ps)
    if rc != 0:
        return {"ok": False, "err": out[:200]}
    last = out.strip().splitlines()[-1]
    d, p = last.split("|")
    return {"ok": True, "done": d == "True", "running": int(p) > 0}


def start_remote(cfg, job):
    os.makedirs(WORK, exist_ok=True)
    jp = os.path.join(WORK, "job.json")
    json.dump(job, open(jp, "w", encoding="utf-8"), ensure_ascii=False)
    rc, out = _ssh(cfg, f'New-Item -ItemType Directory -Force {REMOTE_ROOT} | Out-Null; '
                        f'Remove-Item {REMOTE_ROOT}\\done.json -ErrorAction SilentlyContinue; "ok"')
    if rc != 0:
        raise RuntimeError(f"サーバーに入れない: {out[:200]}")
    if _scp_to(cfg, jp, REMOTE_ROOT + r"\job.json") != 0:
        raise RuntimeError("仕事のファイルを送れなかった")
    script = rf"{REMOTE_CODE_ROOT}\tools\kagoya_treasure_offload.py"
    cmdline = (f'cmd /c set PYTHONIOENCODING=utf-8 && "{REMOTE_PY}" -u "{script}" run '
               f'{REMOTE_ROOT}\\job.json > {REMOTE_ROOT}\\run.log 2>&1')
    ps = ("$r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create "
          f"-Arguments @{{CommandLine='{cmdline}'}}; $r.ReturnValue")
    rc, out = _ssh(cfg, ps)
    if rc != 0 or out.strip().splitlines()[-1:] != ["0"]:
        raise RuntimeError(f"起動に失敗: {out[:200]}")


def pull_and_write(cfg, st) -> int:
    """結果 (ダンプJSON) を取りに行き、mercari_psa10_treasure タブへ書く。"""
    os.makedirs(WORK, exist_ok=True)
    lp = os.path.join(WORK, "result.json")
    if _scp_from(cfg, REMOTE_ROOT + r"\result.json", lp) != 0:
        return 0
    sys.path.insert(0, REPO)
    import run_harvest_mercari_treasure as treasure  # noqa: PLC0415
    from sheet_writer_mercari_search import load_keys_all_tabs  # noqa: PLC0415
    from sheet_writer_mercari_seller import open_seller_staging_sheet  # noqa: PLC0415

    dump = json.load(open(lp, encoding="utf-8"))
    cands = dump.get("candidates") or []
    unreadable = dump.get("unreadable") or []
    if not cands and not unreadable:
        return 0
    job = json.load(open(os.path.join(WORK, "job.json"), encoding="utf-8"))
    limits = job.get("card_limits") or {}
    known = load_keys_all_tabs(open_seller_staging_sheet())
    items = treasure._treasure_items(cands, unreadable, limits)
    res = treasure.append_treasure_items(items, known_keys=known)
    print(f"  [SHEET] {res}")
    return res.get("appended", 0)


def cycle() -> int:
    """取りに行く → サーバーが空いていて今日の分が未だなら、送って開始する。

    頻度は毎日 (治療ハントは7時間前後かかるが、1件ごとの区切り判定で
    サーバーが混む時は途中で止まり、次のcycleで続きから進む)。
    """
    cfg = _cfg()
    st = _state()
    today = datetime.date.today().isoformat()
    rs = remote_status(cfg)
    if not rs["ok"]:
        print(f"⚠ サーバーに入れない: {rs.get('err')} — 今回は何もしない")
        st["last_error"] = f"{datetime.datetime.now():%m/%d %H:%M} サーバーに入れない"
        _save_state(st)
        return 1
    if rs["done"]:
        n = pull_and_write(cfg, st)
        if n:
            print(f"📥 {n}件をスプシに書いた")
        _ssh(cfg, f'Remove-Item {REMOTE_ROOT}\\result.json,{REMOTE_ROOT}\\done.json -ErrorAction SilentlyContinue')
        st["job_date"] = st.get("pending_date")
        st.pop("pending_date", None)
        _save_state(st)
        return 0
    if rs["running"]:
        print("⏳ サーバーで実行中")
        return 0
    if st.get("job_date") == today:
        print("✅ 今日の分は済み")
        return 0
    if st.get("pending_date") == today:
        print("⚠️ 前回の起動が続いていない (即死の可能性) → 作り直して再送")
        st.pop("pending_date", None)
    if remote_busy(cfg):
        print("⏸ サーバーでHQの補探索が動いている → 今回は待つ")
        return 0
    sync_code(cfg, st)
    job = build_job(today)
    if not job["keywords"]:
        print("一覧が空 → 何もしない")
        st["job_date"] = today
        _save_state(st)
        return 0
    start_remote(cfg, job)
    st["pending_date"] = today
    st["started"] = datetime.datetime.now().isoformat(timespec="seconds")
    st.pop("last_error", None)
    _save_state(st)
    print(f"🚀 サーバーで開始した (検索語 {len(job['keywords'])})")
    return 0


def status():
    st = _state()
    print(json.dumps(st, ensure_ascii=False, indent=1))
    try:
        print(remote_status(_cfg()))
    except Exception as e:  # noqa: BLE001
        print(f"サーバー: 確認できず ({type(e).__name__})")


def main():
    a = sys.argv[1:]
    if not a:
        print(__doc__)
        return 0
    if a[0] == "run":
        run_job(a[1])
        return 0
    if a[0] == "cycle":
        return cycle()
    if a[0] == "status":
        status()
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
