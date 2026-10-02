"""kagoya_chara_offload - キャラ軸トレジャーハント収集を KAGOYA サーバーで回す.

2026-10-01 [IMPLEMENT-GO] (`2026-10-01_kagoya_chara_harvest_go.md`)。
HQ の `iMakHQ/tools/kagoya_offload.py` と同じ形 (置き場・鍵の扱いは別)。

家とサーバーの分担:
  - 家   : 対象キーワード (`chara_market.csv`) とスプシの既知キー (dedupe用) を読んで
           仕事のファイルを作り送る → サーバーの結果 (ダンプJSON) を取りに行き、
           `sheet_writer_mercari_seller.append_chara_items()` でスプシに書く。
           **スプシ・eBay の鍵はサーバーに置かない**
  - 鯖   : 仕事のファイル (キーワード一覧・既知キー・仕入上限) を受け取り、未ログインの
           Chrome (`chrome_profile_mercari_seller_anon` 相当) で検索・詳細取得・ラベルVision判定
           をして、結果をダンプJSONに逐次保存する (`run_harvest_mercari_psa10.collect` の
           `_save()` が元から1語/10件ごとに書く)。**スプシへは書かない** (`--no-dedupe` 相当で
           Google Sheets 関連コードを呼ばない)

サーバー側の置き場は HQ の `C:\\setup\\offload` とは別 (`C:\\setup\\harvest_offload`)。
コードの展開先も別 (`C:\\dev\\iMak_harvest_offload`)。接続情報 (host/user/鍵) は HQ と同じ
サーバーなので `C:/dev/iMak_data/hq/offload.json` を読むだけ (mode フィールドは使わない)。

メモリ4GBのサーバーで HQ の補探索 (Chrome 1本) と重ならないよう、起動前に
サーバー側で kagoya_offload.py run / chara の python が動いていないか見て、動いていれば待つ。

使い方 (家):
  python tools/kagoya_chara_offload.py cycle     # 結果を取りに行く → 空いていれば今週の分を送って開始
  python tools/kagoya_chara_offload.py status
使い方 (サーバー。家の cycle が起動する):
  python tools/kagoya_chara_offload.py run C:\\setup\\harvest_offload\\job.json
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import subprocess
import sys
import tarfile
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)  # iMakHarvest/

HQ_OFFLOAD_CONFIG = r"C:/dev/iMak_data/hq/offload.json"
STATE_PATH = r"C:/dev/iMak_data/harvest/kagoya_chara_state.json"
WORK = r"C:/dev/iMak_data/harvest/kagoya_chara_work"

REMOTE_ROOT = r"C:\setup\harvest_offload"
REMOTE_PY = r"C:\Program Files\Python311\python.exe"
REMOTE_CODE_ROOT = r"C:\dev\iMak_harvest_offload"

# サーバー1本の体力(メモリ4GB)に合わせ、HQ の補探索と同時に走らせない。
# (ファイル名のみで判定。 コマンドラインはファイル名の直後に閉じ引用符が入るため
# " run" まで含めると絶対に一致しない。 "kagoya_chara_offload.py" に
# "kagoya_offload.py" は部分一致しない(間に "chara_" が挟まる)ので自分には誤反応しない)
REMOTE_BUSY_MARKERS = ("kagoya_offload.py",)


# ---------------------------------------------------------------------------
# サーバーの席 (2026-10-01 ユーザー確定 `C:/dev/iMak_data/hq/kagoya_server_rules.md` 改訂版
#   「負荷を見ながら、順番と並走を考えて、リソース有効活用して」)。
#   席は空きメモリで取る (札1枚ではない)。 参照実装は HQ の
#   `iMakHQ/tools/kagoya_offload.py` の acquire_server_seat/release_server_seat
#   (担当ごとに置き場が別なので、 ここにそのまま写す。 共有importはしない)。
# ---------------------------------------------------------------------------
SEAT_DIR = r"C:\setup\seats"
# ★2026-10-02 [IMPLEMENT-GO] 段階②: 詳細取得(写真URL等)もAPI版に切替 (フェーズ①は
# 検索のみ済・4af98acb)。 Chrome driver はAPIで足りない時だけ lazy起動 (run_harvest_
# mercari_psa10.collect の detail_fn 配線)。 0.3 は「ほぼAPIで済むが稀にフォールバックで
# Chromeが立つ」実態に合わせた値 (0.2=完全無Chrome の理論値ではなく、 フォールバック分の
# 余地を残す)。
HARVEST_NEED_GB = 0.3
SEARCH_BACKEND = "api"  # "api" | "chrome" — 切り戻しはここを "chrome" に戻すだけ
DETAIL_BACKEND = "api"  # "api" | "chrome" — 切り戻しはここを "chrome" に戻すだけ
MEM_RESERVE_GB = 0.4   # 席を取る時に残す余裕 (kagoya_server_rules.md と同じ値)
PAUSE_RESERVE_GB = 0.3  # 動いている最中、これを切ったら区切って止まる (同上)
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
    """席が空いているか (純関数)。無い/壊れている/持ち主が死んでいる → 空き。"""
    if not isinstance(seat, dict) or not seat.get("pid"):
        return True
    return not pid_alive(seat["pid"])


def can_take_seat(need_gb, free_gb, reserve_gb=MEM_RESERVE_GB) -> bool:
    """空きメモリで席を取れるか (純関数)。"""
    return free_gb - need_gb >= reserve_gb


def acquire_server_seat(owner, need_gb=HARVEST_NEED_GB, seat_dir=SEAT_DIR, free_gb=None, pid_alive=None):
    """席を取る。取れたら True。同じ担当の席が生きていれば取らない。空きメモリが足りなければ取らない。"""
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
    """優先順③の開始条件: HQ の席がある (今日の分が動いている) か、 今日の分が終わった。"""
    return _hq_seat_alive() or hq_today_done()


def should_pause_now() -> bool:
    """1件ごとに見る区切り条件 (kagoya_server_rules.md): HQ.wait がある (2時間以内)、
    または空きメモリが 0.3GB を切った。 どちらかで True → 呼出側がそこで打ち切る。"""
    if os.path.exists(HQ_WAIT_PATH):
        try:
            since = json.load(open(HQ_WAIT_PATH, encoding="utf-8")).get("since")
            age_h = (datetime.datetime.now() - datetime.datetime.fromisoformat(since)).total_seconds() / 3600
            if age_h <= HQ_WAIT_MAX_HOURS:
                return True
        except Exception:  # noqa: BLE001
            return True  # 読めない印は「ある」扱い (待つ側に倒す)
    return free_gb_win() < PAUSE_RESERVE_GB


# ---------------------------------------------------------------------------
# サーバー側
# ---------------------------------------------------------------------------
def run_job(job_path: str) -> None:
    """仕事のファイルを受け取り、収集してダンプJSONへ逐次保存する (スプシへは書かない)。

    優先順③ (キャラ収集など): HQ の席がある/今日の分が終わった時だけ始め、
    空きメモリで自分の席 (`seats/HARVEST.json`) を取れた時だけ動く。
    取れなければ何もせず終わる (結果は壊さない。 次回の呼出で続きから)。
    """
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
        except Exception:  # noqa: BLE001 - 壊れていたら最初から
            resume = None

    from pathlib import Path  # noqa: PLC0415
    chara_args = _server_chara_args(job)

    from scrapers.mercari_search_api import (  # noqa: PLC0415
        ApiSearchClient, collect_multi_keyword_urls_api, fetch_detail_api,
    )
    api_client = ApiSearchClient() if (SEARCH_BACKEND == "api" or DETAIL_BACKEND == "api") else None

    urls_override = None
    if SEARCH_BACKEND == "api":
        api_res = collect_multi_keyword_urls_api(
            job["keywords"], price_min=chara_args.price_min, price_max=chara_args.price_max,
            cap_per_keyword=chara_args.cap_per_keyword, client=api_client,
            progress_callback=lambda n, m: print(f"  {m}", flush=True))
        urls_override = api_res["urls"]
        print(f"[run] 検索(API版): {len(urls_override)} URL (dedup後) "
              f"/ 失敗語 {len(api_res.get('errors') or {})}", flush=True)
        if api_res.get("errors"):
            print(f"  ⚠ API失敗語: {list(api_res['errors'].items())[:5]}", flush=True)

    def _detail_fn(url):
        try:
            return fetch_detail_api(api_client, url)
        except Exception as e:  # noqa: BLE001 - 読めなければ Chrome にフォールバック
            print(f"  ⚠ 詳細(API版)失敗 ({type(e).__name__}) → この1件はChromeで読む", flush=True)
            return None

    detail_fn = _detail_fn if DETAIL_BACKEND == "api" else None

    kill_chrome_for_profile(MS.CHROME_PROFILE_DIR_ANON)
    kill_orphan_chromedriver()
    try:
        payload = psa10.collect(chara_args, dump_path=Path(dump_path_str), resume=resume, on_flush=None,
                                should_pause=should_pause_now, urls_override=urls_override,
                                detail_fn=detail_fn)
    finally:
        if api_client is not None:
            api_client.close()
        kill_chrome_for_profile(MS.CHROME_PROFILE_DIR_ANON)
        kill_orphan_chromedriver()

    unfinished = bool(payload.get("truncated"))
    print(f"[run] {'区切って終了' if unfinished else '完了'}: 候補 {len(payload['candidates'])}件 / "
          f"番号読めず {len(payload.get('unreadable') or [])}件", flush=True)
    if unfinished:
        return  # done.json は書かない (全語終わっていない。 続きは次回 run_job が resume する)
    json.dump({"finished": datetime.datetime.now().isoformat(timespec="seconds")},
              open(os.path.join(d, "done.json"), "w", encoding="utf-8"))


def _server_chara_args(job):
    """家から受け取った job (keywords/known_keys/cost_max_jpy) から collect() 用の引数を作る.

    `no_dedupe=True` にして Google Sheets 関連コード (sheet_writer.load_claimed_supply、
    鍵が要る) を呼ばない。 既に押さえてある分の除外は、家が取り込み時に
    `append_chara_items(known_keys=...)` でやる (二重に落ちても正しさは変わらない。
    サーバー側でVision代を少し余計に使うだけ)。
    """
    import argparse  # noqa: PLC0415

    return argparse.Namespace(
        keywords=job["keywords"], games=None, from_demand=False, demand_only=False, demand_limit=0,
        headless=True, manual=False, price_min=3000, price_max=70000, min_rating=100,
        no_identity=False, cap_per_keyword=100, keyword_interval=8.0, max_details=0,
        no_dedupe=True, save_every=10, sheet_every=10_000_000,  # サーバーではスプシ書込しない
        max_consecutive_errors=3, strict_gates=True,
        cost_cfg={"max_jpy": job["cost_max_jpy"]}, card_limits={},
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
    """同期する .py 一覧 (iMakHarvest 直下 + scrapers/ 配下 + このファイル自身)。"""
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
    """今日の仕事を作る (家で。 スプシ・共有領域を読むだけ)。"""
    sys.path.insert(0, REPO)
    from scrapers import chara_keywords  # noqa: PLC0415
    import run_harvest_mercari_psa10 as psa10  # noqa: PLC0415
    from sheet_writer_mercari_search import load_keys_all_tabs  # noqa: PLC0415
    from sheet_writer_mercari_seller import open_seller_staging_sheet  # noqa: PLC0415

    rows = chara_keywords.load_rows()
    keywords = chara_keywords.build_keywords(rows)
    cost_cfg = psa10.load_cost_sanity()
    known = load_keys_all_tabs(open_seller_staging_sheet())
    return {"job_id": f"chara-{today}", "keywords": keywords,
            "cost_max_jpy": cost_cfg["max_jpy"], "known_keys": sorted(known)}


def remote_busy(cfg) -> bool:
    """サーバーで HQ の補探索か、このジョブが既に動いているか。 分からない時は True (待つ側)。

    ★2026-10-01 事故: コマンドラインには `kagoya_offload.py" run` のように
    ファイル名の直後に閉じ引用符が入るため、 Python 側の単純な部分文字列一致
    (`"kagoya_offload.py run" in out`) は絶対に一致しなかった (HQの補探索と
    キャラ収集が同時に動きサーバーのメモリを使い切った)。 `-like '*...*'` の
    ワイルドカードで PowerShell 側で判定する (remote_status と同じ方式)。
    """
    conds = " -or ".join(f"$_.CommandLine -like '*{m}*'" for m in REMOTE_BUSY_MARKERS)
    ps = (f'$n = @(Get-CimInstance Win32_Process -Filter "Name=\'python.exe\'" | '
          f'Where-Object {{ {conds} }}).Count; "$n"')
    rc, out = _ssh(cfg, ps)
    if rc != 0:
        return True
    try:
        return int(out.strip().splitlines()[-1]) > 0
    except Exception:  # noqa: BLE001 - 読めなければ待つ側に倒す
        return True


def remote_status(cfg) -> dict:
    ps = (f'$d = Test-Path {REMOTE_ROOT}\\done.json; '
          f'$p = @(Get-CimInstance Win32_Process -Filter "Name=\'python.exe\'" | '
          f'Where-Object {{ $_.CommandLine -like \'*kagoya_chara_offload.py*run*\' }}).Count; "$d|$p"')
    rc, out = _ssh(cfg, ps)
    if rc != 0:
        return {"ok": False, "err": out[:200]}
    last = out.strip().splitlines()[-1]
    d, p = last.split("|")
    return {"ok": True, "done": d == "True", "running": int(p) > 0}


def start_remote(cfg, job):
    """仕事を送って起動する。 `result.json` は消さない — 落ちた後の再送で `run_job` が
    これを読んで続きから再開する (2026-10-01 事故対応: 殺した後の再送で消すと
    収集済み分が丸ごと消える)。 `done.json` だけ消す (前回「完了」の印を残さない)。"""
    os.makedirs(WORK, exist_ok=True)
    jp = os.path.join(WORK, "job.json")
    json.dump(job, open(jp, "w", encoding="utf-8"), ensure_ascii=False)
    rc, out = _ssh(cfg, f'New-Item -ItemType Directory -Force {REMOTE_ROOT} | Out-Null; '
                        f'Remove-Item {REMOTE_ROOT}\\done.json -ErrorAction SilentlyContinue; "ok"')
    if rc != 0:
        raise RuntimeError(f"サーバーに入れない: {out[:200]}")
    if _scp_to(cfg, jp, REMOTE_ROOT + r"\job.json") != 0:
        raise RuntimeError("仕事のファイルを送れなかった")
    script = rf"{REMOTE_CODE_ROOT}\tools\kagoya_chara_offload.py"
    cmdline = (f'cmd /c set PYTHONIOENCODING=utf-8 && "{REMOTE_PY}" -u "{script}" run '
               f'{REMOTE_ROOT}\\job.json > {REMOTE_ROOT}\\run.log 2>&1')
    ps = ("$r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create "
          f"-Arguments @{{CommandLine='{cmdline}'}}; $r.ReturnValue")
    rc, out = _ssh(cfg, ps)
    if rc != 0 or out.strip().splitlines()[-1:] != ["0"]:
        raise RuntimeError(f"起動に失敗: {out[:200]}")


def pull_and_write(cfg, st) -> int:
    """結果 (ダンプJSON) を取りに行き、スプシへ書く。 書けた件数を返す。"""
    os.makedirs(WORK, exist_ok=True)
    lp = os.path.join(WORK, "result.json")
    if _scp_from(cfg, REMOTE_ROOT + r"\result.json", lp) != 0:
        return 0
    sys.path.insert(0, REPO)
    import run_harvest_mercari_chara as chara  # noqa: PLC0415
    import run_harvest_mercari_psa10 as psa10  # noqa: PLC0415
    from sheet_writer_mercari_search import load_keys_all_tabs  # noqa: PLC0415
    from sheet_writer_mercari_seller import open_seller_staging_sheet  # noqa: PLC0415

    dump = json.load(open(lp, encoding="utf-8"))
    cands = dump.get("candidates") or []
    unreadable = dump.get("unreadable") or []
    if not cands and not unreadable:
        return 0
    known = load_keys_all_tabs(open_seller_staging_sheet())
    res = chara.append_chara_items(psa10.build_sheet_items(cands, unreadable), known_keys=known)
    print(f"  [SHEET] {res}")
    return res.get("appended", 0)


def cycle() -> int:
    """取りに行く → サーバーが空いていて今週の分が未だなら、送って開始する。"""
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
        st["job_week"] = st.get("pending_week")
        st.pop("pending_week", None)
        _save_state(st)
        return 0
    if rs["running"]:
        print("⏳ サーバーで実行中")
        return 0
    # 週1回だけ起動 (ISO週番号が変わったら次の週)
    this_week = datetime.date.today().isocalendar()[:2]
    this_week_key = f"{this_week[0]}-W{this_week[1]:02d}"
    if st.get("job_week") == this_week_key:
        print("✅ 今週の分は済み")
        return 0
    if st.get("pending_week") == this_week_key:
        # 起動済のはずが実行中でも完了でもない = 起動に失敗して即死した。 作り直して再送
        print("⚠️ 前回の起動が続いていない (即死の可能性) → 作り直して再送")
        st.pop("pending_week", None)
    if remote_busy(cfg):
        print("⏸ サーバーでHQの補探索が動いている → 今回は待つ")
        return 0
    sync_code(cfg, st)
    job = build_job(today)
    if not job["keywords"]:
        print("一覧が空 → 何もしない")
        st["job_week"] = this_week_key
        _save_state(st)
        return 0
    start_remote(cfg, job)
    st["pending_week"] = this_week_key
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
