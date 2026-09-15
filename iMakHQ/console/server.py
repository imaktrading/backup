# -*- coding: utf-8 -*-
"""出品くん Console — Web 画面のサーバー (2026-09-15 段階1: ホーム画面)。

ユーザー「もっと有料システムみたいな感じで」→ 見本に「こういうのを求めている」→ 「うん」(作る)。
今の出品くん (control_panel.py) は **書き換えない**。部品として読み込み、同じ定義・同じ集計を使う:
  ・ボタン          … control_panel.SCRIPTS (badge を持つもの)
  ・残り件数        … counts.py (control_panel と同じ count_workload を別プロセスで呼ぶ)
  ・棚割り / 評価   … control_panel._fetch_consolidated_counts / _fetch_seller_stats
  ・夜間の結果      … control_panel.nightly_last_run
  ・担当の状況      … tools/worktree_board.py の出力
押せるのは **後処理の無いボタンだけ** (runnable)。CSV の後処理 (除外・タイトル補強・重複チェック) を
持つボタンは、同じ流れを移すまで「今のパネルで」と出す。

起動: pythonw server.py  (Edge のアプリ窓で http://127.0.0.1:8765/ を開く。既に動いていれば窓だけ開く)
"""
import datetime
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
HQ = os.path.dirname(HERE)
TOOLS = os.path.join(HQ, "tools")
STATIC = os.path.join(HERE, "static")
HOST = "127.0.0.1"                      # 自分の PC からだけ開ける
PORT = int(os.environ.get("CONSOLE_PORT", "8765"))
COUNTS_CACHE = r"C:/dev/iMak_data/hq/console_counts.json"
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
HOME_TTL = 10 * 60
CREW_TTL = 3 * 60
TASKS_TTL = 5 * 60

# 夜間バッチが減らしてくれる種類 (control_panel の act_kind と同じ)。夜が動いている日は「夜間で自動」
NIGHT_KINDS = {"hoju_search", "ut_search", "ut_restock_search", "kuji_search"}
STEP_RE = re.compile(r"[①②③④⑤]")


# ---------------------------------------------------------------- 純関数 (test 可)

def display_label(label):
    """ボタン名の頭の絵文字を落とす (画面は絵文字を使わない)。"""
    return re.sub(r"^[^\w]+", "", label or "").strip()


def runnable(script):
    """この画面から押してよいボタンか。後処理・入力欄・確認画面・新規出品は今のパネルで押す。"""
    return bool(script.get("skip_postprocess")
                and not script.get("params")
                and not script.get("ask_amount")
                and not script.get("custom_buttons")
                and not script.get("restock_revise")
                and script.get("type") != "new")


def group_of(label):
    if "補URL" in label:
        return "hoju"
    if "再仕入れ" in label or "売れた分" in label:
        return "restock"
    if "取下げ" in label or "棚" in label:
        return "shelf"
    return "seed"


def _num(x):
    if isinstance(x, (list, tuple, set, dict)):
        return len(x)
    try:
        return int(x or 0)
    except (TypeError, ValueError):
        return 0


def summarize(d, nightly_ok=False):
    """counts.py の結果 → {種類: {n, state, note}}。state = todo / night / hold / done / error。

    何を「押さないと減らない」とするかは control_panel の act_kind と同じ。
    """
    d = d if isinstance(d, dict) else {}
    out = {}

    def put(kind, n, todo, note="", hold=0):
        if todo and kind in NIGHT_KINDS and nightly_ok:
            state = "night"
        elif todo:
            state = "todo"
        elif hold:
            state = "hold"
        else:
            state = "done"
        out[kind] = {"n": n, "state": state, "note": note, "hold": hold}

    def err(kinds, part):
        for k in kinds:
            out[k] = {"n": None, "state": "error", "note": str(part.get("error"))[:90], "hold": 0}

    h = d.get("hoju") or {}
    hk = ("hoju_search", "hoju_search_now", "hoju_confirm", "hoju_swap")
    if h.get("error"):
        err(hk, h)
    elif h:
        s, cf, sw = h.get("search") or {}, h.get("confirm") or {}, h.get("swap") or {}
        put("hoju_search", _num(s.get("can")), bool(s.get("can")), "今夜また探す分")
        put("hoju_search_now", _num(s.get("today_can")), bool(s.get("today_can")), "今日出した分")
        n = _num(cf.get("ready")) + _num(cf.get("unjudged"))
        put("hoju_confirm", n, n > 0, "補が少ない → ウォッチ多い順")
        n = _num(sw.get("ready")) + _num(sw.get("unjudged"))
        put("hoju_swap", n, n > 0, "¥1,000 以上安い候補だけ")

    u = d.get("ut") or {}
    uk = ("ut_search", "ut_search_now", "ut_confirm", "ut_swap_confirm",
          "ut_restock_search", "ut_restock_confirm", "ut_restore")
    if u.get("error"):
        err(uk, u)
    elif u:
        put("ut_search", _num(u.get("search")), bool(u.get("search")))
        put("ut_search_now", _num(u.get("search")), bool(u.get("search")), "出した直後に押す分")
        put("ut_confirm", _num(u.get("confirm")), bool(u.get("confirm")))
        put("ut_swap_confirm", _num(u.get("swap_confirm")), bool(u.get("swap_confirm")))
        put("ut_restock_search", _num(u.get("restock_search")), bool(u.get("restock_search")),
            "売り切れた出品の仕入れ直し")
        put("ut_restock_confirm", _num(u.get("restock_confirm")), bool(u.get("restock_confirm")))
        put("ut_restore", _num(u.get("restore")), bool(u.get("restore")))

    for key, kind, field in (("ut_identify", "ut_identify", "pending"),
                             ("newcand_high", "newcand_high", "pending")):
        p = d.get(key) or {}
        if p.get("error"):
            err((kind,), p)
        elif p:
            put(kind, _num(p.get(field)), bool(p.get(field)))

    nc = d.get("newcand") or {}
    if nc.get("error"):
        err(("newcand",), nc)
    elif nc:
        n = _num(nc.get("show")) + _num(nc.get("auto"))
        put("newcand", n, n > 0)

    kj = d.get("kuji") or {}
    kk = ("kuji_search", "kuji_confirm", "kuji_supply", "kuji_refresh")
    if kj.get("error"):
        err(kk, kj)
    elif kj:
        for kind, part, field in (("kuji_search", "search", "can"), ("kuji_confirm", "confirm", "ready"),
                                  ("kuji_supply", "supply", "can"), ("kuji_refresh", "refresh", "can")):
            v = (kj.get(part) or {}).get(field)
            put(kind, None if v is None else _num(v), bool(v))

    for key, kind, fields, hold_field in (
            ("cull", "cull_end", ("remaining",), None),
            ("shelf", "shelf_evict", ("picked",), None),
            ("restock", "sold_restock", ("actionable", "unknown"), "blocked"),
            ("psa_gate", "psa_gate", ("actionable", "variant_todo"), None),
            ("restock_build", "restock_build", ("actionable",), "blocked"),
            ("restock_wb", "restock_wb", ("actionable",), None)):
        p = d.get(key) or {}
        if p.get("error"):
            err((kind,), p)
        elif p:
            n = sum(_num(p.get(f)) for f in fields)
            hold = _num(p.get(hold_field)) if hold_field else 0
            put(kind, n, n > 0, ("止めている %d件" % hold) if hold and not n else "", hold)
    return out


def shelf_looks_unread(shelf_rows):
    """棚割りが「読めなかった」形か (純関数)。

    ★2026-09-15 実測: control_panel._fetch_consolidated_counts は統合シートの読込に失敗すると
      **黙って 0行** を返す。残件の数え直しと同時に読むと 429 で2枚とも空になり、公式在庫シートの
      件数だけが残って「全カテゴリ $0 / TCG 0件」が正しい数字のように出た。
      出品中があるのに金額の合計が 0 = 読めていない、と判定して画面にそう出す。
    """
    rows = shelf_rows or []
    return sum(r.get("count", 0) for r in rows) > 0 and sum(r.get("usd", 0.0) for r in rows) == 0


def parse_crew(text):
    """worktree_board.py の出力 → [{name, body, flag}] (control_panel と同じ読み方)。"""
    rows, route = [], 0
    for ln in (text or "").splitlines():
        s = ln.strip()
        if s.startswith("## 🔀"):
            m = re.search(r"(\d+)件", s)
            route = int(m.group(1)) if m else 0
            continue
        m = re.match(r"^## (.+?) — (.*)$", s)
        if m:
            body = m.group(2)
            flag = ("act" if re.search(r"(自分が返す|窓口宛) [1-9]", body)
                    else "review" if re.search(r"レビュー待ち [1-9]", body) else "")
            rows.append({"name": m.group(1).strip(), "body": body.strip(), "flag": flag})
    return {"rows": rows, "route": route}


# ---------------------------------------------------------------- 状態

_LOCK = threading.Lock()
STATE = {
    "counts": None, "counts_at": None, "counting": False, "counts_error": "",
    "home": None, "home_at": 0, "home_loading": False,
    "crew": None, "crew_at": 0,
    "tasks": None, "tasks_at": 0,
    "job": None,            # {kind, label, started, rc, running}
    "log": [],              # [(seq, text)]
    "seq": 0,
}


def _cp():
    if HQ not in sys.path:
        sys.path.insert(0, HQ)
    import control_panel
    return control_panel


def _log(text):
    with _LOCK:
        for line in str(text).rstrip("\n").split("\n"):
            STATE["seq"] += 1
            STATE["log"].append((STATE["seq"], line))
        del STATE["log"][:-3000]


def _load_counts_cache():
    try:
        with open(COUNTS_CACHE, encoding="utf-8") as f:
            c = json.load(f)
        STATE["counts"], STATE["counts_at"] = c.get("d"), c.get("at")
    except (OSError, ValueError):
        pass


def refresh_counts():
    """counts.py を別プロセスで走らせて保存 (同じタブを何度も読まない SHEET_READ_MEMO=1)。"""
    with _LOCK:
        if STATE["counting"]:
            return
        STATE["counting"] = True
    try:
        r = subprocess.run([sys.executable, "-X", "utf8", os.path.join(HERE, "counts.py")],
                           capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=240, cwd=TOOLS,
                           env=dict(os.environ, PYTHONIOENCODING="utf-8", SHEET_READ_MEMO="1"),
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        out = (r.stdout or "").strip().splitlines()
        d = json.loads(out[-1]) if out else None
        if not isinstance(d, dict):
            raise RuntimeError(((r.stderr or "").strip().splitlines() or ["出力なし"])[-1][:120])
        at = datetime.datetime.now().isoformat(timespec="seconds")
        STATE["counts"], STATE["counts_at"], STATE["counts_error"] = d, at, ""
        os.makedirs(os.path.dirname(COUNTS_CACHE), exist_ok=True)
        with open(COUNTS_CACHE, "w", encoding="utf-8") as f:
            json.dump({"at": at, "d": d}, f, ensure_ascii=False)
    except Exception as e:                                     # noqa: BLE001
        STATE["counts_error"] = "%s: %s" % (type(e).__name__, e)
    finally:
        STATE["counting"] = False
        STATE["home_at"] = 0                         # 数え終わってからホームを読み直す


def _home_worker():
    cp = _cp()
    home = {"shelf": [], "month": {}, "stats": {}, "nightly": {}, "errors": []}
    try:
        month = datetime.date.today().strftime("%Y-%m")
        counts = cp._fetch_consolidated_counts(month)
        cats = list(cp.CATEGORY_BUDGET_USD) + [c for c in counts if c not in cp.CATEGORY_BUDGET_USD]
        m_usd = m_cnt = 0
        total_usd = 0.0
        for c in cats:
            sc = counts.get(c) or cp._empty_cat()
            usd = float(sc.get("usd", 0.0) or 0)
            total_usd += usd
            m_usd += float(sc.get("monthly_usd", 0.0) or 0)
            m_cnt += int(sc.get("monthly", 0) or 0)
            home["shelf"].append({"cat": c, "budget": cp.CATEGORY_BUDGET_USD.get(c), "usd": usd,
                                  "count": int(sc.get("current", 0) or 0),
                                  "monthly_usd": float(sc.get("monthly_usd", 0.0) or 0),
                                  "monthly": int(sc.get("monthly", 0) or 0)})
        home["month"] = {"usd": m_usd, "count": m_cnt, "shelf_usd": total_usd,
                         "shelf_budget": cp.SHELF_BUDGET_TOTAL_USD}
    except Exception as e:                                     # noqa: BLE001
        home["errors"].append("棚割り: %s" % e)
    try:
        home["nightly"] = cp.nightly_last_run() or {}
    except Exception as e:                                     # noqa: BLE001
        home["errors"].append("夜間: %s" % e)
    try:
        home["stats"] = cp._fetch_seller_stats(cp._get_ebay_token()) or {}
        home["stats"]["seller"] = cp.EBAY_SELLER
    except Exception as e:                                     # noqa: BLE001
        home["errors"].append("eBay: %s" % e)
    home["shelf_unread"] = shelf_looks_unread(home["shelf"])
    retry_at = time.time()
    if home["shelf_unread"]:
        cp._CACHED_SHEET_COUNTS["data"] = None      # パネルの1分キャッシュに空の結果を残さない
        home["errors"].append("棚割り: 統合シートを読めませんでした (読み取り上限の可能性)。1分後に読み直します")
        retry_at = time.time() - HOME_TTL + 60
    STATE["home"], STATE["home_at"], STATE["home_loading"] = home, retry_at, False


def get_home():
    # 残件の数え直しと同時に読まない (同じスプシを読んで 1分の読み取り上限に当たる)
    if ((STATE["home"] is None or time.time() - STATE["home_at"] > HOME_TTL)
            and not STATE["home_loading"] and not STATE["counting"]):
        STATE["home_loading"] = True
        threading.Thread(target=_home_worker, daemon=True).start()
    return {"home": STATE["home"], "loading": STATE["home_loading"]}


def _crew_worker():
    try:
        r = subprocess.run([sys.executable, "-X", "utf8", os.path.join(TOOLS, "worktree_board.py")],
                           capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=120, env=dict(os.environ, PYTHONIOENCODING="utf-8"),
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        STATE["crew"] = parse_crew(r.stdout)
    except Exception as e:                                     # noqa: BLE001
        STATE["crew"] = {"rows": [], "route": 0, "error": str(e)}
    STATE["crew_at"] = time.time()


def get_crew():
    if STATE["crew"] is None or time.time() - STATE["crew_at"] > CREW_TTL:
        STATE["crew_at"] = time.time()
        threading.Thread(target=_crew_worker, daemon=True).start()
    return STATE["crew"] or {"rows": [], "route": 0, "loading": True}


def get_jobs():
    cp = _cp()
    nightly = (STATE["home"] or {}).get("nightly") or {}
    summ = summarize(STATE["counts"], nightly_ok=bool(nightly.get("done")))
    jobs = []
    for s in cp.SCRIPTS:
        kind = s.get("badge")
        if not kind or kind == "hoju_status":
            continue
        label = display_label(s["label"])
        m = STEP_RE.search(label)
        info = summ.get(kind) or {"n": None, "state": "unknown", "note": "", "hold": 0}
        jobs.append({"kind": kind, "label": label, "step": m.group(0) if m else "",
                     "group": group_of(label), "tip": (s.get("tip") or "")[:160],
                     "runnable": runnable(s), **info})
    return {"jobs": jobs, "counts_at": STATE["counts_at"], "counting": STATE["counting"],
            "counts_error": STATE["counts_error"]}


def get_buttons():
    """今の出品くんのボタン一覧 (新規出品の商材カード・各ページの表を、パネルと同じ並びで作る)。"""
    cp = _cp()
    out = []
    for i, s in enumerate(cp.SCRIPTS):
        out.append({"i": i, "type": s.get("type"), "category": s.get("category"),
                    "label": display_label(s["label"]), "badge": s.get("badge"),
                    "runnable": runnable(s), "tip": (s.get("tip") or "")[:160]})
    return {"buttons": out}


def _tasks_worker():
    ps = ("Get-ScheduledTask | Where-Object { $_.TaskName -like '*iMak*' } | Get-ScheduledTaskInfo | "
          "Select-Object TaskName,LastRunTime,LastTaskResult,NextRunTime | ConvertTo-Json -Compress")
    rows = []
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                           capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=90, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        data = json.loads(r.stdout or "[]")
        for t in (data if isinstance(data, list) else [data]):
            rows.append({"name": t.get("TaskName"), "last": _ps_date(t.get("LastRunTime")),
                         "next": _ps_date(t.get("NextRunTime")), "result": t.get("LastTaskResult")})
        rows.sort(key=lambda x: x["last"] or "", reverse=True)
    except Exception as e:                                     # noqa: BLE001
        STATE["tasks"] = {"tasks": [], "error": str(e)}
        STATE["tasks_at"] = time.time()
        return
    STATE["tasks"], STATE["tasks_at"] = {"tasks": rows}, time.time()


def _ps_date(v):
    """ConvertTo-Json の日付 (/Date(ミリ秒)/ または ISO 文字列) → 'MM/DD HH:MM'。"""
    if not v:
        return ""
    m = re.search(r"/Date\((-?\d+)", str(v))
    try:
        dt = (datetime.datetime.fromtimestamp(int(m.group(1)) / 1000) if m
              else datetime.datetime.fromisoformat(str(v)[:19]))
    except (ValueError, OSError, OverflowError):
        return str(v)[:16]
    return "—" if dt.year < 2000 else dt.strftime("%m/%d %H:%M")


def get_tasks():
    if STATE["tasks"] is None or time.time() - STATE["tasks_at"] > TASKS_TTL:
        STATE["tasks_at"] = time.time()
        threading.Thread(target=_tasks_worker, daemon=True).start()
    return STATE["tasks"] or {"tasks": [], "loading": True}


def run_job(kind):
    cp = _cp()
    script = next((s for s in cp.SCRIPTS if s.get("badge") == kind), None)
    if not script:
        return 404, {"error": "そのボタンはありません"}
    if not runnable(script):
        return 409, {"error": "このボタンは後処理があるので、今の出品くんで押してください"}
    with _LOCK:
        if STATE["job"] and STATE["job"].get("running"):
            return 409, {"error": "「%s」が実行中です。終わってから押してください" % STATE["job"]["label"]}
        STATE["job"] = {"kind": kind, "label": display_label(script["label"]),
                        "started": datetime.datetime.now().strftime("%H:%M:%S"), "rc": None, "running": True}
    threading.Thread(target=_run_worker, args=(script,), daemon=True).start()
    return 200, {"ok": True}


def _run_worker(script):
    label = display_label(script["label"])
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1", **(script.get("env") or {}))
    _log("▶ %s  (%s)" % (label, " ".join(script["cmd"])))
    fh = None
    try:
        fh, path = _cp()._open_run_log(script["label"])
        fh.write("=== %s (%s) console ===\ncwd: %s\ncmd: %s\n\n" % (
            script["label"], time.strftime("%Y-%m-%d %H:%M:%S"), script["cwd"], " ".join(script["cmd"])))
        _log("  記録: %s" % path)
    except Exception:                                          # noqa: BLE001
        fh = None
    rc = None
    try:
        p = subprocess.Popen(list(script["cmd"]), cwd=script["cwd"], env=env,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                             encoding="utf-8", errors="replace", bufsize=1,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        for line in p.stdout:
            _log(line)
            if fh:
                fh.write(line)
                fh.flush()
        rc = p.wait()
    except Exception as e:                                     # noqa: BLE001
        _log("起動できませんでした: %s" % e)
    finally:
        if fh:
            fh.close()
    _log(("✓ 終わりました: %s" % label) if rc == 0 else ("✗ 失敗しました (returncode=%s): %s" % (rc, label)))
    with _LOCK:
        STATE["job"].update(rc=rc, running=False)
    refresh_counts()


# ---------------------------------------------------------------- HTTP

_TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
          ".js": "application/javascript; charset=utf-8", ".svg": "image/svg+xml"}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):                                 # 画面の読み込みで記録を汚さない
        pass

    def _json(self, code, obj):
        b = json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/api/home":
            return self._json(200, get_home())
        if u.path == "/api/jobs":
            return self._json(200, get_jobs())
        if u.path == "/api/crew":
            return self._json(200, get_crew())
        if u.path == "/api/buttons":
            return self._json(200, get_buttons())
        if u.path == "/api/tasks":
            return self._json(200, get_tasks())
        if u.path == "/api/log":
            after = int((parse_qs(u.query).get("after") or ["0"])[0] or 0)
            with _LOCK:
                lines = [(s, t) for s, t in STATE["log"] if s > after]
                job = dict(STATE["job"]) if STATE["job"] else None
            return self._json(200, {"lines": lines, "job": job})
        name = "index.html" if u.path in ("/", "") else u.path.lstrip("/")
        path = os.path.normpath(os.path.join(STATIC, name))
        if not path.startswith(STATIC) or not os.path.isfile(path):
            return self._json(404, {"error": "not found"})
        with open(path, "rb") as f:
            b = f.read()
        self.send_response(200)
        self.send_header("Content-Type", _TYPES.get(os.path.splitext(path)[1], "application/octet-stream"))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_POST(self):
        # 別のサイトから勝手に押されないよう、画面が付ける合図が無い要求は断る
        if self.headers.get("X-Console") != "1":
            return self._json(403, {"error": "forbidden"})
        u = urlparse(self.path)
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}") if n else {}
        if u.path == "/api/run":
            code, obj = run_job(str(body.get("kind") or ""))
            return self._json(code, obj)
        if u.path == "/api/refresh":
            threading.Thread(target=refresh_counts, daemon=True).start()
            STATE["crew_at"] = 0                     # ホームは数え終わってから読む (refresh_counts)
            return self._json(200, {"ok": True})
        return self._json(404, {"error": "not found"})


def _port_in_use(port):
    with socket.socket() as s:
        return s.connect_ex((HOST, port)) == 0


def open_window():
    url = "http://%s:%d/" % (HOST, PORT)
    try:
        subprocess.Popen([EDGE, "--app=" + url])
    except OSError:
        import webbrowser
        webbrowser.open(url)


def main():
    if _port_in_use(PORT):                                     # もう動いている = 窓だけ開く
        if "--no-open" not in sys.argv:
            open_window()
        return
    _load_counts_cache()
    threading.Thread(target=get_home, daemon=True).start()
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    if "--no-open" not in sys.argv:
        threading.Timer(0.6, open_window).start()
    srv.serve_forever()


if __name__ == "__main__":
    main()
