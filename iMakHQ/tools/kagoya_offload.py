"""補URL探索を KAGOYA のサーバーで回す (2026-10-01 ユーザー確定: 重い探索はサーバーへ)。

このPC (家) とサーバーの分担:
  - 家   : 対象を選んで検索語を作る (スプシ・カタログ DB を読む) → 仕事のファイルを送る
           → サーバーの結果を取りに行き、控えに書く。**スプシや eBay の鍵はサーバーに置かない**
  - 鯖   : 仕事のファイルに並んだ検索を1件ずつ流し、結果を1行ずつ書く (途中で落ちても続きから)

探す間隔 (2026-10-01 ユーザー確定「補は売り切れ防止と最安値入れ替えで一番重要。鮮度は
いいに越したことはないが、無駄な稼働はいらない」):
  - 補0〜3本 (売り切れ防止)      : 毎日
  - 再仕入れ候補 (先読み)        : 毎日
  - 補4〜5本 (安い仕入元への入替): SWAP_EVERY_DAYS 日に1回
  空振りが続く出品は、家の夜の検索と同じ台帳 (hoju_dry_streak.json) で間隔を空ける。

段階 (本番の控えに書くのはユーザーの go の後だけ):
  - mode=shadow (既定): 結果は kagoya_research_cache.json に書く。本番の psa_research_cache.json
                        と空振り台帳には触らない。`compare` で家の結果と並べて比べる
  - mode=live         : 本番の控えに書く (家の夜の検索は「今日済み」を飛ばすので、残りだけ探す)

使い方 (家):
  python kagoya_offload.py cycle     # 結果を取りに行く → サーバーが空いていて今日の分が未だなら送って開始
  python kagoya_offload.py status
  python kagoya_offload.py compare   # shadow の結果と家の結果を並べる
使い方 (サーバー。家の cycle が起動する):
  python kagoya_offload.py run C:\\setup\\offload\\job.json
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

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))

CONFIG_PATH = r"C:/dev/iMak_data/hq/offload.json"
STATE_PATH = r"C:/dev/iMak_data/hq/offload_state.json"
SHADOW_CACHE_PATH = os.path.join(HERE, "kagoya_research_cache.json")
WORK = os.path.join(r"C:/dev/iMak_data/hq", "offload_work")

SWAP_EVERY_DAYS = 2           # 補4〜5本は2日に1回 (2〜3日に1回の案の短い方)
DESC_LIMIT = 400              # 説明の番号読み (家の夜は200件。未読が約1,300件あるので倍に)
UT_EVERY_DAYS = 3             # UT の補・再仕入れ先は週2回ほど (8晩で使える候補3本だったため毎晩はやめる)
SNKR_SLEEP = 1.0
MERCARI_BATCH = 8             # 家の夜の検索と同じ。この件数ごとに結果を書く

REMOTE_ROOT = r"C:\setup\offload"
REMOTE_PY = r"C:\Program Files\Python311\python.exe"
REMOTE_CODE_ROOT = r"C:\dev\iMak"
REMOTE_DB = r"C:\dev\iMak_data\catalog\products.sqlite"
LOCAL_DB = r"C:/dev/iMak_data/catalog/products.sqlite"
# DB の外にある、探す時に読むカタログのデータ (家の置き場, サーバーの置き場)
DATA_FILES = [
    (r"C:/dev/iMak_data/catalog/op_variant_official_map.json",
     r"C:\dev\iMak_data\catalog\op_variant_official_map.json"),
]


# ---------------------------------------------------------------------------
# 純関数 (テスト対象)
# ---------------------------------------------------------------------------
def needs_search(entry, today, every_days):
    """その出品を今日探すか。entry = 控えの1件 (date を持つ)。純関数。

    - 控えが無い / 日付が読めない → 探す
    - 最後に探した日から every_days 日以上たった → 探す
    - mercari が取れていない (前回は取得失敗) → 探す (取れなかっただけを「無い」にしない)
    """
    if not isinstance(entry, dict) or "mercari" not in entry:
        return True
    d = entry.get("date")
    try:
        age = (datetime.date.fromisoformat(today) - datetime.date.fromisoformat(str(d))).days
    except Exception:
        return True
    return age >= every_days


def plan_job(fill, swap, restock, cache, dry, today, should_skip_dry, swap_every=SWAP_EVERY_DAYS):
    """今日サーバーに頼む対象を並べる。純関数。

    並び: 売り切れ防止 (補0〜3本) → 再仕入れ候補 → 入れ替え (補4〜5本)。同じ出品は1回だけ。
    空振りが続く出品は外す (家の夜の検索と同じ台帳・同じ判定)。
    Returns: (targets, counts)
    """
    out, seen = [], set()
    counts = {"fill": 0, "restock": 0, "swap": 0, "dry_skip": 0, "fresh_skip": 0}
    for kind, group, every in (("fill", fill, 1), ("restock", restock, 1), ("swap", swap, swap_every)):
        for t in group or []:
            iid = t.get("itemID")
            if not iid or iid in seen:
                continue
            seen.add(iid)
            if not needs_search(cache.get(iid), today, every):
                counts["fresh_skip"] += 1
                continue
            if should_skip_dry(dry.get(iid), today):
                counts["dry_skip"] += 1
                continue
            out.append({**t, "kind": kind})
            counts[kind] += 1
    return out, counts


def done_item_ids(result_lines, key="itemID"):
    """結果ファイル (1行1件の JSON) から、もう済んだ物 (既定は itemID) を集める。壊れた行は無視。純関数。"""
    done = set()
    for line in result_lines:
        line = line.strip()
        if not line:
            continue
        try:
            done.add(json.loads(line)[key])
        except Exception:
            continue
    return done


def has_candidate(mercari, snkr):
    """候補が1件でも出たか (空振り台帳の判定。家の夜の検索と同じ)。純関数。"""
    m = mercari if isinstance(mercari, dict) else {}
    return bool(m.get("all_cands") or m.get("cands") or m.get("best")
                or (isinstance(snkr, dict) and snkr.get("available")))


# ---------------------------------------------------------------------------
# サーバー側
# ---------------------------------------------------------------------------
def run_job(job_path):
    """仕事のファイルを1件ずつ流す。結果は1件ごとに追記 = 落ちても続きから。"""
    try:
        import certifi
        os.environ.setdefault("SSL_CERT_FILE", certifi.where())
    except Exception:
        pass
    sys.path.insert(0, HERE)
    sys.path.insert(0, REPO)
    import mercari_psa_resource as mp
    import snkrdunk_psa_resource as sp

    job = json.load(open(job_path, encoding="utf-8"))
    wait_path = os.path.join(SEAT_DIR, "HQ.wait")
    # ★2026-10-02: 急ぎの探索 (数件・メルカリは API) は Chrome を使わないので軽い席で取る
    if not acquire_server_seat("HQ", need_gb=float(job.get("need_gb") or HQ_NEED_GB)):
        # 優先順の低い仕事 (抽出くん等) はこの印を見たら区切りの良い所で止まって席を空ける (続きは後で)
        os.makedirs(SEAT_DIR, exist_ok=True)
        json.dump({"since": datetime.datetime.now().isoformat(timespec="seconds")},
                  open(wait_path, "w", encoding="utf-8"))
        print("[run] 席が取れない (同じ仕事が動いている / 空きメモリ不足) → 待ちの印を置いて今回は動かない", flush=True)
        return
    try:
        os.remove(wait_path)
    except OSError:
        pass
    try:
        _run_job_body(job, job_path, mp, sp)
    finally:
        release_server_seat("HQ")


def _run_job_body(job, job_path, mp, sp):
    res_path = os.path.join(os.path.dirname(job_path), "result.jsonl")
    done_path = os.path.join(os.path.dirname(job_path), "done.json")
    lines = open(res_path, encoding="utf-8").read().splitlines() if os.path.exists(res_path) else []
    done = done_item_ids(lines)
    todo = [t for t in job["targets"] if t["itemID"] not in done]
    print(f"[run] job={job['job_id']} 全{len(job['targets'])}件 / 済{len(done)} / 残り{len(todo)}", flush=True)
    t0 = time.time()
    for s in range(0, len(todo), MERCARI_BATCH):
        grp = todo[s:s + MERCARI_BATCH]
        cards = [{**t["q"], "ebay_item_id": t["itemID"]} for t in grp]
        try:
            m = mp.fetch_mercari_cheapest(cards, freeship_min_reviews=100)
        except Exception as e:                                   # noqa: BLE001
            print(f"  ⚠ メルカリ batch 失敗 ({type(e).__name__}) — この束はスニダンのみ", flush=True)
            m = {}
        with open(res_path, "a", encoding="utf-8") as f:
            for j, t in enumerate(grp):
                q = t["q"]
                try:
                    snkr = sp.check_by_keyword(q.get("card_no"), variant_hint=q.get("hint"),
                                               multi_variant=q.get("multi_variant"))
                except Exception as e:                           # noqa: BLE001
                    snkr = {"_error": str(e)[:40] or "error", "available": False, "psa10_price_jpy": None}
                mres = m.get(j) if j in m else {"_error": "batch_failed"}
                f.write(json.dumps({"itemID": t["itemID"], "kind": t.get("kind"),
                                    "date": job["date"], "mercari": mres, "snkrdunk": snkr},
                                   ensure_ascii=False, default=str) + "\n")
                f.flush()
                time.sleep(SNKR_SLEEP)
        print(f"  💾 {min(s + MERCARI_BATCH, len(todo))}/{len(todo)} ({round(time.time() - t0)}秒)", flush=True)
    _run_desc(job, os.path.dirname(job_path))
    _run_ut(job, os.path.dirname(job_path))
    _run_stock(job, os.path.dirname(job_path))
    _run_kuji(job, os.path.dirname(job_path))
    json.dump({"job_id": job["job_id"], "finished": datetime.datetime.now().isoformat(timespec="seconds"),
               "sec": round(time.time() - t0)}, open(done_path, "w", encoding="utf-8"))
    print("[run] 完了", flush=True)


# ---------------------------------------------------------------------------
# サーバーの席 (2026-10-01 ユーザー「負荷を見ながら、順番と並走を考えて、リソース有効活用して」
#   「ただ動かすだけなら、メモリいくつあっても足りない」「24時間専用マシーンなんだから」)
#   仕事は始める時に「席」を取る。席が取れるのは **空きメモリが need_gb + 余裕 以上ある時だけ**。
#   空きがあれば担当をまたいで並べて動き、無ければ待つ (次の回に続きから)。
#   実測 (4GB): Windows 約2GB / Chrome を使う仕事1本 約1.1GB → 今の大きさでは Chrome の仕事は実質1本ずつ。
#   24時間あるので時間で分ける: HQ の補探索は日付が変わったら最初 (約5時間)、ほかの担当はその後の約19時間。
#   優先順: ①監視くんの予備 (割り込み可) ②HQ ③抽出くんのキャラ収集など (HQ が席を取った後・終わった後)
#   席: SEAT_DIR/<担当>.json = {"owner", "pid", "need_gb", "started"}。pid が死んだ席は無効。
# ---------------------------------------------------------------------------
SEAT_DIR = r"C:\setup\seats"
HQ_NEED_GB = 1.2
URGENT_NEED_GB = 0.4          # 急ぎの探索 (数件・API のみ。画像検索に落ちた時だけ Chrome)
MEM_RESERVE_GB = 0.4


def _pid_alive_win(pid):
    try:
        import ctypes
        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))
        if not h:
            return False
        code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(h)
        return code.value == 259
    except Exception:
        return False


def free_gb_win():
    try:
        import ctypes

        class MS(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("total", ctypes.c_ulonglong), ("avail", ctypes.c_ulonglong),
                        ("a", ctypes.c_ulonglong), ("b", ctypes.c_ulonglong), ("c", ctypes.c_ulonglong),
                        ("d", ctypes.c_ulonglong), ("e", ctypes.c_ulonglong)]
        m = MS()
        m.dwLength = ctypes.sizeof(m)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        return m.avail / 1024 ** 3
    except Exception:
        return 0.0


def lock_is_free(lock, pid_alive):
    """席が空いているか (純関数)。無い / 壊れている / 持ち主が死んでいる → 空き。"""
    if not isinstance(lock, dict) or not lock.get("pid"):
        return True
    return not pid_alive(lock["pid"])


def can_take_seat(need_gb, free_gb, reserve_gb=MEM_RESERVE_GB):
    """空きメモリで席を取れるか (純関数)。"""
    return free_gb - need_gb >= reserve_gb


def acquire_server_seat(owner, need_gb=HQ_NEED_GB, seat_dir=SEAT_DIR, free_gb=None, pid_alive=None):
    """席を取る。取れたら True。同じ担当の席が生きていれば取らない。空きメモリが足りなければ取らない。"""
    pid_alive = pid_alive or _pid_alive_win
    os.makedirs(seat_dir, exist_ok=True)
    path = os.path.join(seat_dir, owner + ".json")
    if os.path.exists(path):
        try:
            cur = json.load(open(path, encoding="utf-8"))
        except Exception:
            cur = None
        if not lock_is_free(cur, pid_alive):
            return False
        try:
            os.remove(path)
        except OSError:
            return False
    fg = free_gb_win() if free_gb is None else free_gb
    if not can_take_seat(need_gb, fg):
        print(f"[seat] 空きメモリ {fg:.2f}GB / 要る {need_gb}GB + 余裕 {MEM_RESERVE_GB}GB → 今は始めない", flush=True)
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
    except Exception:
        pass


def _done_keys(path, key):
    if not os.path.exists(path):
        return set()
    return done_item_ids(open(path, encoding="utf-8").read().splitlines(), key)


def _run_desc(job, d):
    """メルカリの商品説明に書いてある番号を読む (mercari_desc_numbers と同じ読み方)。"""
    urls = job.get("desc_urls") or []
    if not urls:
        return
    import undetected_chromedriver as uc
    import mercari_desc_numbers as MDN
    from mercari_psa_resource import _chrome_major, _quiet_chromedriver
    rp = os.path.join(d, "desc_result.jsonl")
    done = _done_keys(rp, "url")
    todo = [u for u in urls if u not in done]
    print(f"[desc] 全{len(urls)}件 / 済{len(done)} / 残り{len(todo)}", flush=True)
    if not todo:
        return
    drv = None

    def _chrome():
        _quiet_chromedriver()
        o = uc.ChromeOptions()
        for a in ("--headless=new", "--lang=ja-JP", "--window-size=1280,1400"):   # ログインしない
            o.add_argument(a)
        maj = _chrome_major()
        return uc.Chrome(options=o, version_main=maj) if maj else uc.Chrome(options=o)
    try:
        with open(rp, "a", encoding="utf-8") as f:
            for n, u in enumerate(todo, 1):
                # ★2026-10-02: まず API (Chrome を開かない)。読めない物だけ Chrome
                ent = MDN.read_description_api(u)
                if ent is None:
                    if drv is None:
                        drv = _chrome()
                    ent = MDN.read_description(drv, u)
                if ent is None:
                    continue                    # 読めなかった分は書かない (次の回にまた読む)
                f.write(json.dumps({"url": u, "entry": ent}, ensure_ascii=False) + "\n")
                f.flush()
                if n % 50 == 0:
                    print(f"  📝 {n}/{len(todo)}", flush=True)
    finally:
        try:
            drv.quit()
        except Exception:                                        # noqa: BLE001
            pass


def _run_ut(job, d):
    """UT の補URL・再仕入れ先を探す (ut_hoju_fill と同じ探し方)。"""
    groups = job.get("ut") or {}
    if not any(groups.values()):
        return
    import mercari_psa_resource as mp
    import ut_hoju_fill as U
    rp = os.path.join(d, "ut_result.jsonl")
    done = {(json.loads(x).get("sold_out"), json.loads(x).get("itemID"))
            for x in (open(rp, encoding="utf-8").read().splitlines() if os.path.exists(rp) else [])
            if x.strip().startswith("{")}
    class _Lazy:                       # ★2026-10-02: 検索・詳細は API。読めない時だけ Chrome を起こす
        _d = None

        def __getattr__(self, name):
            if self._d is None:
                self._d = U._new_driver()
            return getattr(self._d, name)

        def quit(self):
            if self._d is not None:
                self._d.quit()
    drv = _Lazy()
    try:
        with open(rp, "a", encoding="utf-8") as f:
            for sold_out, key in ((False, "fill"), (True, "restock")):
                ts = [t for t in groups.get(key) or [] if (sold_out, t["itemID"]) not in done]
                print(f"[ut-{key}] 残り{len(ts)}件", flush=True)
                for t in ts:
                    ent = U.search_one(drv, t, mp, job["date"])
                    if ent is None:
                        continue
                    f.write(json.dumps({"itemID": t["itemID"], "sold_out": sold_out, "entry": ent},
                                       ensure_ascii=False, default=str) + "\n")
                    f.flush()
    finally:
        try:
            drv.quit()
        except Exception:                                        # noqa: BLE001
            pass


# ★2026-10-02: 一番くじの夜の検索 (run_kuji_night.py・家で約8分・Chrome) を KAGOYA で回す。
#   読み書きする控え (家の置き場 = サーバーの置き場)。送る時の写しを base に取っておき、
#   戻ってきた時は「サーバーで変わった項目だけ」を家の今のファイルに書く (昼にボタンで書いた分を消さない)。
KUJI_FILES = [
    r"C:/dev/iMak_data/dedupe/ichibankuji_identify_cache.json",
    r"C:/dev/iMak_data/dedupe/ichibankuji_detail_cache.json",
    r"C:/dev/iMak_data/dedupe/ichibankuji_candidate_wait.json",
    r"C:/dev/iMak_data/hq/not_buyable_urls.json",
]
KUJI_BASE = os.path.join(WORK, "kuji_base")


def merge_changed(base, srv, home):
    """サーバーで変わった (足された / 中身が変わった) 項目だけを home に書く。純関数 (home の写しを返す)。

    消えた項目は消さない (サーバーで消したのか、送る前から無かったのか区別しない = 消さない側)。
    """
    out = dict(home or {})
    for k, v in (srv or {}).items():
        if k not in (base or {}) or base[k] != v:
            out[k] = v
    return out


def _run_kuji(job, d):
    """一番くじの夜の検索 (候補を集める + 詳細を取る)。画面なしの Chrome で。"""
    if not job.get("kuji"):
        return
    mark = os.path.join(d, "kuji_done.json")
    if os.path.exists(mark):
        return
    print("[kuji] 一番くじの夜の検索", flush=True)
    t0 = time.time()
    started = datetime.datetime.now()
    try:
        r = subprocess.run([sys.executable, "-X", "utf8", os.path.join(HERE, "run_kuji_night.py")],
                           cwd=HERE, env=dict(os.environ, PYTHONIOENCODING="utf-8", IMAK_HEADLESS="1"))
        rc = r.returncode
    finally:
        # ★2026-10-02: 途中で止まると一番くじの Chrome (16個・約900MB) が残り、一日中 席が取れなかった。
        #   この回に起動した、一番くじ用の Chrome だけを閉じる (他の担当・前からある物には触らない)
        _close_own_chrome("ichibankuji_scrape_profile", started)
    json.dump({"job_id": job["job_id"], "rc": rc, "sec": round(time.time() - t0)},
              open(mark, "w", encoding="utf-8"))


def _close_own_chrome(profile_word, since):
    """サーバーで、since 以降に起動した profile_word の Chrome だけを閉じる (Windows・自分の仕事の後片付け)。"""
    ps = ("Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'chrome.exe' -and "
          f"$_.CommandLine -match '{profile_word}' -and "
          f"$_.CreationDate -ge [datetime]'{since:%Y-%m-%dT%H:%M:%S}' }} | "
          "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }")
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", ps], timeout=60,
                       capture_output=True, text=True)
    except Exception:                                          # noqa: BLE001
        pass


def _push_kuji_files(cfg):
    """一番くじの控えをサーバーへ送り、送った時点の写しを base に残す。"""
    os.makedirs(KUJI_BASE, exist_ok=True)
    for p in KUJI_FILES:
        b = os.path.join(KUJI_BASE, os.path.basename(p))
        data = _load_json(p)
        json.dump(data, open(b, "w", encoding="utf-8"), ensure_ascii=False)
        rp = p.replace("/", "\\")
        rc, _ = _ssh(cfg, f'New-Item -ItemType Directory -Force "{os.path.dirname(rp)}" | Out-Null; "ok"')
        if _scp_to(cfg, b, rp) != 0:
            raise RuntimeError(f"{os.path.basename(p)} を送れなかった")


def _pull_kuji(cfg, st, job):
    """一番くじの結果を取りに行き、変わった項目だけ家の控えに書く。1つの仕事につき1回だけ。"""
    if not job.get("kuji") or st.get("kuji_merged") == job.get("job_id"):
        return 0
    lp = os.path.join(WORK, "kuji_done.json")
    if _scp_from(cfg, REMOTE_ROOT + r"\kuji_done.json", lp) != 0:
        return 0                                   # まだ終わっていない
    n = 0
    for p in KUJI_FILES:
        tmp = os.path.join(WORK, "kuji_srv_" + os.path.basename(p))
        if _scp_from(cfg, p.replace("/", "\\"), tmp) != 0:
            continue
        base = _load_json(os.path.join(KUJI_BASE, os.path.basename(p)))
        srv, home = _load_json(tmp), _load_json(p)
        out = merge_changed(base, srv, home)
        n += sum(1 for k in out if home.get(k) != out[k])
        t = p + ".tmp"
        json.dump(out, open(t, "w", encoding="utf-8"), ensure_ascii=False)
        os.replace(t, p)
    st["kuji_merged"] = job.get("job_id")
    st.setdefault("covered", {})["kuji"] = job.get("date")
    print(f"  🎯 一番くじ: 家の控えに {n}項目を書いた ({_load_json(lp)})")
    return n


def _run_stock(job, d):
    """🌱 (捨てた候補→新規出品の種) の目視待ちの在庫を API で先に確かめる (Chrome を使わない)。"""
    urls = job.get("stock_urls") or []
    if not urls:
        return
    import mercari_psa_resource as mp
    rp = os.path.join(d, "stock_result.jsonl")
    done = _done_keys(rp, "url")
    todo = [u for u in urls if u not in done]
    print(f"[stock] 全{len(urls)}件 / 済{len(done)} / 残り{len(todo)}", flush=True)
    for s in range(0, len(todo), 20):
        st, tts, _rest = mp.api_stock_check(todo[s:s + 20])
        with open(rp, "a", encoding="utf-8") as f:
            for u, ok in st.items():                       # 判らなかった分は書かない (家で確かめる)
                f.write(json.dumps({"url": u, "ok": ok, "title": tts.get(u, ""),
                                    "at": datetime.datetime.now().isoformat(timespec="seconds")},
                                   ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# 家の側: 送る・起動・取りに行く
# ---------------------------------------------------------------------------
def _cfg():
    return json.load(open(CONFIG_PATH, encoding="utf-8"))


def _state():
    try:
        return json.load(open(STATE_PATH, encoding="utf-8"))
    except Exception:
        return {}


def _save_state(st):
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
    files = [os.path.join("iMakHQ", "tools", f) for f in os.listdir(HERE) if f.endswith(".py")]
    # ★2026-10-02: 一番くじ等が使う eBay の部品 (ebay_getitem_images / credentials 等)
    ebay = os.path.join(REPO, "iMakeBayAPI")
    files += [os.path.join("iMakeBayAPI", f) for f in os.listdir(ebay) if f.endswith(".py")]
    # 値段の計算 (pricing_engine) が読む設定 (リバイスくんの KAGOYA 影で全件失敗・2026-10-02)
    cdir = os.path.join(ebay, "config")
    if os.path.isdir(cdir):
        files += [os.path.join("iMakeBayAPI", "config", f) for f in os.listdir(cdir)
                  if f.endswith((".yaml", ".yml", ".json"))]
    cat = os.path.join(REPO, "iMakCatalog")
    for dp, dn, fn in os.walk(cat):
        dn[:] = [d for d in dn if d not in ("tests", "__pycache__")]
        if os.path.relpath(dp, cat).count(os.sep) >= 1:
            continue
        files += [os.path.relpath(os.path.join(dp, f), REPO) for f in fn if f.endswith(".py")]
    return sorted(files)


def _code_hash(files):
    h = hashlib.sha256()
    for f in files:
        h.update(f.encode())
        with open(os.path.join(REPO, f), "rb") as fh:
            h.update(fh.read())
    return h.hexdigest()[:16]


def db_is_healthy(path):
    """SQLite の quick_check が ok か (読むだけ)。開けない時も壊れている扱い。"""
    import sqlite3
    try:
        c = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30)
        try:
            return c.execute("pragma quick_check").fetchone()[0] == "ok"
        finally:
            c.close()
    except Exception:                                          # noqa: BLE001
        return False


def sync_code_and_db(cfg, st):
    """コードと DB の写しを、変わった時だけ送る。"""
    os.makedirs(WORK, exist_ok=True)
    rc, out = _ssh(cfg, f'New-Item -ItemType Directory -Force {REMOTE_ROOT},{REMOTE_CODE_ROOT},'
                        f'{os.path.dirname(REMOTE_DB)} | Out-Null; "ok"')
    if rc != 0 or "ok" not in out:
        raise RuntimeError(f"サーバーに置き場を作れない: {out[:200]}")
    files = _code_files()
    ch = _code_hash(files)
    if st.get("code_hash") != ch:
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
    m = os.path.getmtime(LOCAL_DB)
    if st.get("db_mtime") != m and not db_is_healthy(LOCAL_DB):
        # ★2026-10-02: 08:20 に壊れた DB をそのまま KAGOYA に送っていた。壊れた物は送らない
        #   (KAGOYA は前の写しのまま動く)。直った DB は mtime が変わるので次の回に送られる
        print("  ⚠️要対応: カタログ DB が壊れている (quick_check NG) → KAGOYA には送らない")
    elif st.get("db_mtime") != m:
        if _scp_to(cfg, LOCAL_DB, REMOTE_ROOT + r"\products.sqlite") != 0:
            raise RuntimeError("DB を送れなかった")
        rc, out = _ssh(cfg, f'Copy-Item {REMOTE_ROOT}\\products.sqlite {REMOTE_DB} -Force; "ok"')
        if rc != 0 or "ok" not in out:
            raise RuntimeError(f"DB の置き換えに失敗: {out[:200]}")
        st["db_mtime"] = m
        print("  📦 カタログ DB の写しを送った")
    # ★2026-10-01: 探す時に読むカタログのデータファイル (DB の外にある物) も送る。
    #   版の対応表を送っておらず、サーバーでは読み替えずに探していた (無ければ今までどおりの作り)。
    for local, remote in DATA_FILES:
        if not os.path.exists(local):
            continue
        m = os.path.getmtime(local)
        sk = "mtime:" + os.path.basename(local)
        if st.get(sk) == m:
            continue
        tmp = REMOTE_ROOT + "\\" + os.path.basename(local)
        if _scp_to(cfg, local, tmp) != 0:
            raise RuntimeError(f"{os.path.basename(local)} を送れなかった")
        rc, out = _ssh(cfg, f'Copy-Item {tmp} {remote} -Force; "ok"')
        if rc != 0 or "ok" not in out:
            raise RuntimeError(f"{os.path.basename(local)} の置き換えに失敗: {out[:200]}")
        st[sk] = m
        print(f"  📦 {os.path.basename(local)} を送った")


def build_job(today):
    """今日の仕事を作る (家で。スプシ・DB を読むだけ)。"""
    sys.path.insert(0, HERE)
    import psa_hoju_fill as H
    import mercari_psa_resource as mp
    vals = H._read_high()
    watch = H.load_watch_by_item()
    fill = H.select_backfill_targets(vals, max_backups=H.CONFIRM_MAX_BACKUPS, watch=watch)
    swap = H.select_backfill_targets(vals, max_backups=H.AUXN + 1, min_backups=H.CONFIRM_MAX_BACKUPS,
                                     watch=watch)
    try:
        restock = H.restock_targets()
    except Exception as e:                                       # noqa: BLE001
        print(f"  ⚠ 再仕入れ候補を読めず ({type(e).__name__}) — 今日は補だけ")
        restock = []
    cache = H._load_cache() if _mode() == "live" else _merged_view(H)
    # ★2026-10-01 (総点検 ⑧): 入れ替え (補4〜5本) の間隔は offload.json の "swap_every_days" で変えられる
    #   (無ければ SWAP_EVERY_DAYS=2)。KAGOYA の空き時間に余裕があれば 1 にして毎日探す。
    targets, counts = plan_job(fill, swap, restock, cache, H.load_dry(), today, H.should_skip_dry,
                               swap_every=swap_every_days(_cfg()))
    out, no_q = [], 0
    for t in targets:
        q = H.build_search_query(t, mp)
        if not q.get("card_no"):
            no_q += 1
            continue                     # 家の夜の検索と同じ: 番号が取れない物は探さず・控えも汚さない
        out.append({"itemID": t["itemID"], "kind": t["kind"], "q": q})
    counts["no_query"] = no_q
    job = {"job_id": f"{today}-{int(time.time())}", "date": today, "targets": out, "counts": counts}
    if _mode() == "live":
        # 説明の番号読み: 毎日 DESC_LIMIT 件 (家の夜は200件だった)
        try:
            import mercari_desc_numbers as MDN
            job["desc_urls"] = MDN.urls_to_check(H._load_cache(), MDN.load())[:DESC_LIMIT]
        except Exception as e:                                   # noqa: BLE001
            print(f"  ⚠ 番号読みの対象を作れず ({type(e).__name__}) — 今日は家の夜に任せる")
        counts["desc"] = len(job.get("desc_urls") or [])
        # UT の補・再仕入れ先: UT_EVERY_DAYS 日に1回
        if ut_due(_state().get("ut_last"), today, UT_EVERY_DAYS):
            try:
                import ut_hoju_fill as U
                job["ut"] = {"fill": U.plan_targets(sold_out=False), "restock": U.plan_targets(sold_out=True)}
            except Exception as e:                               # noqa: BLE001
                print(f"  ⚠ UT の対象を作れず ({type(e).__name__}) — 今日は家の夜に任せる")
        counts["ut"] = sum(len(v) for v in (job.get("ut") or {}).values())
        # 🌱 の目視待ちの在庫 (切り替え: offload.json の "newcand_stock": true。既定は切)
        if (_cfg().get("newcand_stock") is True):
            try:
                job["stock_urls"] = newcand_stock_urls()
            except Exception as e:                               # noqa: BLE001
                print(f"  ⚠ 🌱 の在庫確認の対象を作れず ({type(e).__name__}) — 昼のボタンで確かめる")
        counts["stock"] = len(job.get("stock_urls") or [])
        # 一番くじの夜の検索 (切り替え: offload.json "kuji_night": true。既定は切 = 鍵を置いてから入れる)
        if _cfg().get("kuji_night") is True:
            job["kuji"] = True
    return job


def swap_every_days(cfg):
    """入れ替えを何日に1回探すか (純関数)。読めない・1未満 → 既定 SWAP_EVERY_DAYS。"""
    try:
        v = int((cfg or {}).get("swap_every_days", SWAP_EVERY_DAYS))
    except (TypeError, ValueError):
        return SWAP_EVERY_DAYS
    return v if v >= 1 else SWAP_EVERY_DAYS


STOCK_SEEN_PATH = r"C:/dev/iMak_data/hq/mercari_stock_seen.json"
STOCK_LIMIT = 1500


def newcand_stock_urls(limit=STOCK_LIMIT):
    """🌱 の目視待ち (未処理) の候補の URL (家で。スプシを読むだけ・書かない)。"""
    import newcand_confirm as NC
    items = NC.load_items(limit=0, write=False, resolve=False)
    urls = []
    for it in items:
        urls.append(it.get("url"))
        urls.extend(dd.get("url") for dd in (it.get("dups") or []))
    return [u for u in dict.fromkeys(NC.mercari_urls(u for u in urls if u))][:limit]


def ut_due(last, today, every):
    """UT を今日探すか (最後に探した日から every 日以上)。純関数。"""
    try:
        return (datetime.date.fromisoformat(today) - datetime.date.fromisoformat(str(last))).days >= every
    except Exception:
        return True


def _mode():
    try:
        return _cfg().get("mode", "shadow")
    except Exception:
        return "shadow"


def _load_json(path):
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception:
        return {}


def _merged_view(H):
    """shadow の時の「最後に探した日」= サーバーの控え (本番の控えは家の夜の検索の分なので見ない)。"""
    return _load_json(SHADOW_CACHE_PATH)


def start_remote(cfg, job):
    """仕事を送って起動する。起動は SSH を切っても続く形 (WMI で別プロセス)。"""
    os.makedirs(WORK, exist_ok=True)
    jp = os.path.join(WORK, "job.json")
    json.dump(job, open(jp, "w", encoding="utf-8"), ensure_ascii=False, default=str)
    rc, out = _ssh(cfg, f'New-Item -ItemType Directory -Force {REMOTE_ROOT} | Out-Null; '
                        f'Remove-Item {REMOTE_ROOT}\\result.jsonl,{REMOTE_ROOT}\\desc_result.jsonl,'
                        f'{REMOTE_ROOT}\\ut_result.jsonl,{REMOTE_ROOT}\\stock_result.jsonl,'
                        f'{REMOTE_ROOT}\\kuji_done.json,'
                        f'{REMOTE_ROOT}\\done.json -ErrorAction SilentlyContinue; "ok"')
    if rc != 0:
        raise RuntimeError(f"サーバーに入れない: {out[:200]}")
    if job.get("kuji"):
        _push_kuji_files(cfg)
    if _scp_to(cfg, jp, REMOTE_ROOT + r"\job.json") != 0:
        raise RuntimeError("仕事のファイルを送れなかった")
    script = rf"{REMOTE_CODE_ROOT}\iMakHQ\tools\kagoya_offload.py"
    cmdline = (f'cmd /c set PYTHONIOENCODING=utf-8 && "{REMOTE_PY}" -u "{script}" run '
               f'{REMOTE_ROOT}\\job.json > {REMOTE_ROOT}\\run.log 2>&1')
    ps = ("$r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create "
          f"-Arguments @{{CommandLine='{cmdline}'}}; $r.ReturnValue")
    rc, out = _ssh(cfg, ps)
    if rc != 0 or out.strip().splitlines()[-1:] != ["0"]:
        raise RuntimeError(f"起動に失敗: {out[:200]}")


def remote_status(cfg):
    """サーバーの今: running / done / idle と、結果の行数。"""
    ps = (f'$d = Test-Path {REMOTE_ROOT}\\done.json; '
          f'$n = if (Test-Path {REMOTE_ROOT}\\result.jsonl) {{ (Get-Content {REMOTE_ROOT}\\result.jsonl | Measure-Object -Line).Lines }} else {{ 0 }}; '
          f'$p = @(Get-CimInstance Win32_Process -Filter "Name=\'python.exe\'" | Where-Object {{ $_.CommandLine -like \'*kagoya_offload.py*run*\' }}).Count; '
          # ★2026-10-01: ほかの担当 (抽出くんのキャラ収集など) の仕事。メモリ 4GB なので重ねない
          f'$o = @(Get-CimInstance Win32_Process -Filter "Name=\'python.exe\'" | Where-Object {{ $_.CommandLine -like \'*_offload.py*run*\' -and $_.CommandLine -notlike \'*kagoya_offload.py*\' }}).Count; '
          '"$d|$n|$p|$o"')
    rc, out = _ssh(cfg, ps)
    if rc != 0:
        return {"ok": False, "err": out[:200]}
    last = out.strip().splitlines()[-1]
    d, n, p, o = (last.split("|") + ["0"])[:4]
    return {"ok": True, "done": d == "True", "lines": int(n), "running": int(p) > 0, "others": int(o or 0)}


def search_running_in(cmdlines):
    """動いているプロセスのコマンド行の中に、家の補探索 (控えに書く物) があるか。純関数。"""
    return any("psa_hoju_fill.py" in c and (" search" in c or " search-restock" in c)
               for c in cmdlines if c)


def home_search_running():
    """家で補探索 (psa_hoju_fill.py search / search-restock) が動いているか。分からない時は True (書かない側)。"""
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command",
                            "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
                            "ForEach-Object { $_.CommandLine }"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
        return search_running_in(r.stdout.splitlines())
    except Exception:                                            # noqa: BLE001
        return True


def pull_and_merge(cfg, st):
    """結果を取りに行き、控えに書く。shadow は別ファイル、live は本番の控え + 空振り台帳。"""
    os.makedirs(WORK, exist_ok=True)
    lp = os.path.join(WORK, "result.jsonl")
    if _scp_from(cfg, REMOTE_ROOT + r"\result.jsonl", lp) != 0:
        return 0
    sys.path.insert(0, HERE)
    import psa_hoju_fill as H
    import mercari_psa_resource as mp
    job = _load_json(os.path.join(WORK, "job.json"))
    mirror = {t["itemID"]: (t.get("q") or {}).get("mirror") for t in job.get("targets", [])}
    card = {t["itemID"]: (t.get("q") or {}).get("card_no") or "" for t in job.get("targets", [])}
    live = _mode() == "live"
    cache = H._load_cache() if live else _load_json(SHADOW_CACHE_PATH)
    dry = H.load_dry() if live else None
    merged = st.get("merged_ids", {}).get(job.get("job_id"), [])
    merged_set, n = set(merged), 0
    for line in open(lp, encoding="utf-8").read().splitlines():
        try:
            r = json.loads(line)
        except Exception:
            continue
        iid = r.get("itemID")
        if not iid or iid in merged_set:
            continue
        m = H.filter_mercari_result_by_mirror(r.get("mercari"), mirror.get(iid), mp)
        H.merge_search_result(cache, iid, m, r.get("snkrdunk"), r.get("date"))
        if live and not H._mercari_errored(m):
            H.update_dry(dry, iid, has_candidate(m, r.get("snkrdunk")), r.get("date"), card.get(iid, ""))
        merged_set.add(iid)
        n += 1
    if n:
        if live:
            H._save_cache(cache)
            H.save_dry(dry)
        else:
            tmp = SHADOW_CACHE_PATH + ".tmp"
            json.dump(cache, open(tmp, "w", encoding="utf-8"), ensure_ascii=False)
            os.replace(tmp, SHADOW_CACHE_PATH)
    st.setdefault("merged_ids", {})[job.get("job_id")] = sorted(merged_set)
    # 古い job の記録は捨てる (今の job だけ持つ)
    st["merged_ids"] = {k: v for k, v in st["merged_ids"].items() if k == job.get("job_id")}
    if live:
        n += (_pull_desc(cfg, st, job) + _pull_ut(cfg, st, job) + _pull_stock(cfg, st, job)
              + _pull_kuji(cfg, st, job))
    return n


def _pull_stock(cfg, st, job):
    """🌱 の在庫の確認結果を家の台帳に書く。同じ URL は新しい方で上書き。"""
    if not job.get("stock_urls"):
        return 0
    rows = _pull_lines(cfg, "stock_result.jsonl")
    if not rows:
        return 0
    led = _load_json(STOCK_SEEN_PATH)
    for r in rows:
        if r.get("url") and isinstance(r.get("ok"), bool):
            led[r["url"]] = {"ok": r["ok"], "title": r.get("title") or "", "at": r.get("at") or ""}
    tmp = STOCK_SEEN_PATH + ".tmp"
    json.dump(led, open(tmp, "w", encoding="utf-8"), ensure_ascii=False)
    os.replace(tmp, STOCK_SEEN_PATH)
    return len(rows)


def _pull_lines(cfg, name):
    lp = os.path.join(WORK, name)
    if _scp_from(cfg, REMOTE_ROOT + "\\" + name, lp) != 0:
        return []
    out = []
    for line in open(lp, encoding="utf-8").read().splitlines():
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def _pull_desc(cfg, st, job):
    """説明の番号を家の台帳 (mercari_desc_numbers.json) に書く。同じ URL は上書き = 何度取り込んでも同じ。"""
    rows = _pull_lines(cfg, "desc_result.jsonl")
    if not rows:
        return 0
    import mercari_desc_numbers as MDN
    led = MDN.load()
    for r in rows:
        if r.get("url") and isinstance(r.get("entry"), dict):
            led[r["url"]] = r["entry"]
    MDN._save(led)
    return len(rows)


def _pull_ut(cfg, st, job):
    """UT の探索結果を家のキャッシュ (補URL用 / 再仕入れ用) に書く。同じ出品は上書き。"""
    rows = _pull_lines(cfg, "ut_result.jsonl")
    if not rows:
        return 0
    import ut_hoju_fill as U
    for sold_out in (False, True):
        sub = [r for r in rows if bool(r.get("sold_out")) == sold_out and isinstance(r.get("entry"), dict)]
        if not sub:
            continue
        path = U._cache_path(sold_out)
        cache = U.load_cache(path)
        for r in sub:
            cache[r["itemID"]] = r["entry"]
        U.save_cache(cache, path)
    st["ut_last"] = job.get("date")
    return len(rows)


def covered_today(st, kind, today):
    """家の夜の束が、その手順を飛ばしてよいか (今日の分をサーバーが終えて取り込み済み)。純関数。"""
    return (st.get("covered") or {}).get(kind) == today


def cycle():
    """取りに行く → サーバーが空いていて今日の分が未だなら、送って開始する。何度呼んでも安全。"""
    cfg = _cfg()
    st = _state()
    today = datetime.date.today().isoformat()
    rs = remote_status(cfg)
    if not rs["ok"]:
        print(f"⚠ サーバーに入れない: {rs.get('err')} — 今回は何もしない (家の夜の検索がそのまま動く)")
        st["last_error"] = f"{datetime.datetime.now():%m/%d %H:%M} サーバーに入れない"
        _save_state(st)
        return 1
    if rs["lines"]:
        if _mode() == "live" and home_search_running():
            # 家の夜の検索は控えを丸ごと読み書きするので、その最中に書くと消し合う。終わってから取り込む
            print("⏸ 家の補探索が動いている → 今回は取り込まない (結果はサーバーに残っている)")
        else:
            n = pull_and_merge(cfg, st)
            if n:
                print(f"📥 結果 {n}件を控えに書いた ({_mode()})")
    if rs["done"] and _mode() == "live" and not home_search_running():
        # サーバーが今日の分を終えて、取り込みも済んだ → 家の夜の束はその手順を飛ばしてよい
        job0 = _load_json(os.path.join(WORK, "job.json"))
        cov = st.setdefault("covered", {})
        if job0.get("desc_urls"):
            cov["desc"] = job0.get("date")
        # ★2026-10-02: 補URL探索 (補0〜3・5本・再仕入れ) も今日済み → 家の夜の束の探索3つを飛ばす。
        #   その日に出たばかりの出品は、1時間おきの見回り (start_urgent_restock) が KAGOYA で探す
        if job0.get("targets") and "urgent" not in str(job0.get("job_id", "")):
            cov["hoju"] = job0.get("date")
    if rs["running"]:
        print(f"⏳ サーバーで実行中 ({rs['lines']}件済み)")
        _save_state(st)
        return 0
    if st.get("job_date") == today and not rs["done"]:
        # 今日の仕事が途中で止まった (サーバー再起動など) → 続きから再開
        print("↻ 今日の仕事が途中で止まっていた → 続きから再開")
        start_remote_resume(cfg)
        _save_state(st)
        return 0
    if st.get("job_date") == today:
        print("✅ 今日の分は済み")
        # ★2026-10-01 (総点検15): 売り切れで取り下げた出品の次の仕入元を、翌日 0:20 を待たずに探す
        if _cfg().get("urgent_restock", True) is not False:
            try:
                start_urgent_restock(cfg, st, today)
            except Exception as e:                               # noqa: BLE001  急ぎの分は次の回にまた見る
                print(f"  ⚠ 売り切れ分の急ぎの探索を始められず ({type(e).__name__}: {e})")
        _save_state(st)
        return 0
    sync_code_and_db(cfg, st)
    job = build_job(today)
    c = job["counts"]
    print(f"▶ 今日の仕事 {len(job['targets'])}件 (売り切れ防止 {c['fill']} / 再仕入れ {c['restock']} / "
          f"入れ替え {c['swap']} | 鮮度内で今日は不要 {c['fresh_skip']} / 空振り続き {c['dry_skip']} / "
          f"番号が取れない {c['no_query']})")
    if not job["targets"]:
        st["job_date"] = today
        _save_state(st)
        return 0
    start_remote(cfg, job)
    st["job_date"] = today
    st["job_id"] = job["job_id"]
    st["started"] = datetime.datetime.now().isoformat(timespec="seconds")
    st.pop("last_error", None)
    _save_state(st)
    print("🚀 サーバーで開始した")
    return 0


def newly_sold(rows, seen, cell, cols):
    """商品管理シートで「売り切れ」に変わった PSA の出品 (前回見た集合 seen に無い物) → [行]。純関数。

    cols = (B=itemID, D=売り切れ, CATEGORY, CERT, KEY)。itemID・売り切れ印・TCG・証明番号の数字がそろう行だけ。
    """
    B, D, CAT, CERT, KEY = cols
    out = []
    for r in rows:
        iid = cell(r, B)
        if not iid or iid == "9999" or not cell(r, D) or cell(r, CAT) != "TCG":
            continue
        if not str(cell(r, CERT)).strip().isdigit() or iid in seen:
            continue
        out.append(r)
    return out


def start_urgent_restock(cfg, st, today):
    """売り切れに変わった出品だけの小さな仕事を送る (1時間おきの見回りから)。

    初回は今の売り切れを「見た」ことにするだけ (過去の 1,900件を一度に探さない)。
    今日もう探した出品は控えの日付で飛ばす。席が取れなければサーバー側で待ちの印を置き、次の回に続きから。
    """
    sys.path.insert(0, HERE)
    import psa_hoju_fill as H
    import mercari_psa_resource as mp
    vals = H._read_high()
    cols = (H.B, H.D, H.CATEGORY, H.CERT, H.KEY)
    if "sold_seen" not in st:
        st["sold_seen"] = sorted({H._cell(r, H.B) for r in vals[1:] if H._cell(r, H.D) and H._cell(r, H.B)})
        print(f"  (売り切れの見張りを開始: 今の売り切れ {len(st['sold_seen'])}件は見たことにする)")
        return
    seen = set(st["sold_seen"])
    new = newly_sold(vals[1:], seen, H._cell, cols)
    cache = H._load_cache()
    targets = []
    # ★2026-10-02: 補URL が0本で、今日まだ探していない出品 (= 今朝の KAGOYA の仕事の後に出した物)。
    #   家の夜の束の補探索をやめた分を、ここで1時間以内に拾う
    _ids = set()
    dry = H.load_dry()
    for t in H.select_backfill_targets(vals, max_backups=1):
        if (cache.get(t["itemID"]) or {}).get("date") == today:
            continue
        if H.should_skip_dry(dry.get(t["itemID"]), today):
            continue                                   # 空振り続き (朝の仕事と同じ基準で間を空ける)
        q = H.build_search_query(t, mp)
        if q.get("card_no"):
            targets.append({"itemID": t["itemID"], "kind": "fill", "q": q})
            _ids.add(t["itemID"])
    for r in new:
        iid = H._cell(r, H.B)
        if (cache.get(iid) or {}).get("date") == today or iid in _ids:
            continue                                   # 今日もう探した
        t = {"itemID": iid, "key": H._cell(r, H.KEY), "cert": H._cell(r, H.CERT), "title": H._cell(r, H.C)}
        q = H.build_search_query(t, mp)
        if q.get("card_no"):
            targets.append({"itemID": iid, "kind": "restock", "q": q})
    if targets:
        sync_code_and_db(cfg, st)
        nf = sum(1 for t in targets if t["kind"] == "fill")
        job = {"job_id": f"{today}-urgent-{int(time.time())}", "date": today, "targets": targets,
               "need_gb": URGENT_NEED_GB,
               "counts": {"restock": len(targets) - nf, "fill": nf, "urgent": True}}
        start_remote(cfg, job)
        print(f"🚀 急ぎの探索 {len(targets)}件 (売り切れの次の仕入元 {len(targets) - nf} / 補0本の新しい出品 {nf})")
    st["sold_seen"] = sorted(seen | {H._cell(r, H.B) for r in new})


def start_remote_resume(cfg):
    """結果ファイルを消さずに、同じ仕事をもう一度起動する (済んだ分は飛ばされる)。"""
    script = rf"{REMOTE_CODE_ROOT}\iMakHQ\tools\kagoya_offload.py"
    cmdline = (f'cmd /c set PYTHONIOENCODING=utf-8 && "{REMOTE_PY}" -u "{script}" run '
               f'{REMOTE_ROOT}\\job.json >> {REMOTE_ROOT}\\run.log 2>&1')
    ps = ("$r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create "
          f"-Arguments @{{CommandLine='{cmdline}'}}; $r.ReturnValue")
    rc, out = _ssh(cfg, ps)
    if rc != 0 or out.strip().splitlines()[-1:] != ["0"]:
        raise RuntimeError(f"再開の起動に失敗: {out[:200]}")


def compare():
    """shadow の結果と、家の夜の検索の結果を、同じ出品・同じ日付で並べる。"""
    sys.path.insert(0, HERE)
    import psa_hoju_fill as H
    home, srv = H._load_cache(), _load_json(SHADOW_CACHE_PATH)

    def urls(m):
        s = set()
        if isinstance(m, dict):
            for k in ("all_cands", "cands"):
                for c in m.get(k) or []:
                    if isinstance(c, (list, tuple)) and len(c) > 1:
                        s.add(str(c[1]).split("?")[0])
        return s
    same_day = both = overlap = s_only = h_only = snk_same = 0
    for iid, e in srv.items():
        h = home.get(iid)
        if not isinstance(h, dict) or h.get("date") != e.get("date"):
            continue
        same_day += 1
        su, hu = urls(e.get("mercari")), urls(h.get("mercari"))
        if su and hu:
            both += 1
            overlap += bool(su & hu)
        elif su:
            s_only += 1
        elif hu:
            h_only += 1
        snk_same += bool((e.get("snkrdunk") or {}).get("available")) == bool((h.get("snkrdunk") or {}).get("available"))
    print(f"サーバーの控え {len(srv)}件 / 家と同じ日に探した {same_day}件")
    print(f"  両方で候補あり {both} (同じ候補が重なる {overlap}) / サーバーだけ {s_only} / 家だけ {h_only}")
    print(f"  スニダンの判定が同じ {snk_same}/{same_day}")


def status():
    st = _state()
    print(json.dumps({k: v for k, v in st.items() if k != "merged_ids"}, ensure_ascii=False, indent=1))
    try:
        print(remote_status(_cfg()))
    except Exception as e:                                       # noqa: BLE001
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
    if a[0] == "covered":
        # 夜の束から呼ぶ: 0 = サーバーが済ませた (飛ばす) / 1 = 家でやる
        kind, today, st = a[1], datetime.date.today().isoformat(), _state()
        if _mode() != "live":
            return 1
        if kind == "ut":
            ok = bool(st.get("ut_last")) and not ut_due(st.get("ut_last"), today, UT_EVERY_DAYS)
        else:
            ok = covered_today(st, kind, today)
        print(f"[kagoya] {kind}: {'サーバーが済ませた → 家では飛ばす' if ok else '家でやる'}")
        return 0 if ok else 1
    if a[0] == "compare":
        compare()
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
