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

起動: pythonw server.py  (Edge のアプリ窓で http://127.0.0.1:8770/ を開く。既に動いていれば窓だけ開く)
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

import version
import watcher

HERE = os.path.dirname(os.path.abspath(__file__))
HQ = os.path.dirname(HERE)
TOOLS = os.path.join(HQ, "tools")
STATIC = os.path.join(HERE, "static")
HOST = "127.0.0.1"                      # 自分の PC からだけ開ける
PORT = int(os.environ.get("CONSOLE_PORT", "8770"))
# ★2026-09-16: 8765 は **PSA 目視 (post_psa_review)** の物。ここを 8765 にしていたため、
#   PSA の 🤖自動 が目視画面を開いた時に Console が出てしまい、目視ができなかった
#   (Windows は同じポートに後から割り込めるので、エラーも出ずに入れ替わる)。
#   既に使われている: 8765=PSA目視 / 8766=一番くじ / 8788=別の確認画面 / 5324x=単一起動の印
COUNTS_CACHE = r"C:/dev/iMak_data/hq/console_counts.json"
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
HOME_TTL = 10 * 60
CREW_TTL = 3 * 60
TASKS_TTL = 5 * 60

# 「探す」系 = 押すと候補が **増える** のが正常。減らなくても おかしくないので突き合わせない
#   (2026-09-16: PSA 再仕入れ①探す が 3件 → 38件 になり、見張りが誤って記録した)
SEARCH_KINDS = {"hoju_search", "hoju_search_now", "ut_search", "ut_search_now",
                "ut_restock_search", "kuji_search", "kuji_supply", "psa_gate", "newcand"}

# 夜間バッチが減らしてくれる種類 (control_panel の act_kind と同じ)。夜が動いている日は「夜間で自動」
NIGHT_KINDS = {"hoju_search", "ut_search", "ut_restock_search", "kuji_search"}
STEP_RE = re.compile(r"[①②③④⑤]")


# ---------------------------------------------------------------- 純関数 (test 可)

def display_label(label):
    """ボタン名の頭の絵文字を落とす (画面は絵文字を使わない)。"""
    return re.sub(r"^[^\w]+", "", label or "").strip()


def runnable(script):
    """この画面から押してよいボタンか。

    ★2026-09-16 (v0.3.0): 走る前のガード (before_run) と走った後の後処理 (after_run) を
      control_panel から抜き出して共用にしたので、**後処理のあるボタン・新規生成も押せる**。
      入力欄 (params) と金額 (ask_amount) は画面で聞いてから渡す。
      残る旧パネル専用は **ウィザード画面が要る物だけ** (一番くじの新規)。
    """
    return not script.get("custom_buttons")


def group_of(label):
    # ★2026-09-19 ユーザー「オファーの件、重要だからTOP画面に出してほしい」。
    #   まとまりが無いと 今日やること の枠に入らず、新規出品の側に紛れていた。
    if "オファー" in label:
        return "offer"
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
        # ★2026-09-16 ユーザー「今日やることは、私がボタンを押すものだけにした方が良くない？
        #   本来動くべきが動いていなかったのは分かった方がいいけど、だからと言って私が何かする
        #   わけでもないし」: 夜が動かす物は **夜が転んだ日も** 作業カードにしない (灰のまま)。
        #   夜が止まったことは 今日やること の上に「知らせ」として1行出す (画面側)。
        if todo and kind in NIGHT_KINDS:
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
        put("ut_search_now", _num(u.get("search_today")), bool(u.get("search_today")),
            "今日出した分")
        put("ut_confirm", _num(u.get("confirm")), bool(u.get("confirm")))
        put("ut_swap_confirm", _num(u.get("swap_confirm")), bool(u.get("swap_confirm")))
        put("ut_restock_search", _num(u.get("restock_search")), bool(u.get("restock_search")),
            "売り切れた出品の仕入れ直し")
        put("ut_restock_confirm", _num(u.get("restock_confirm")), bool(u.get("restock_confirm")))
        put("ut_restore", _num(u.get("restore")), bool(u.get("restore")))

    # ★2026-09-16: UT 目視は3種類が混ざる (新しい候補 / 出品待ち / 出品済みで KEY 無し)。
    #   合計だけ出すと「KEY 埋めが何百件も残っている」と読めてしまうので内訳を添える
    ui = d.get("ut_identify") or {}
    if ui.get("error"):
        err(("ut_identify",), ui)
    elif ui:
        put("ut_identify", _num(ui.get("pending")), bool(ui.get("pending")),
            "出品済みの KEY 埋め (🤖自動が拾う 新候補 %d / 出品待ち %d は別)"
            % (_num(ui.get("new")), _num(ui.get("waiting"))))

    for key, kind, field in (("newcand_high", "newcand_high", "pending"),):
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
            # ★2026-09-16: 「判定できない分」は件数に入れない。押しても動かせないため
            #   (実測: 要対応2件と出ていたが、中身は売れて終了した UK ミラーで、走行は必ず飛ばす)。
            #   件数は **押して動かせる分だけ**。判定できない分は下の note に出す。
            ("restock", "sold_restock", ("actionable",), "blocked"),
            # ★2026-09-20 ユーザー「4件と表示されているけど、押すと1件しか出てこない」。
            #   このボタンは **2段** ある: ①変種の目視ゲート → (答えてから) ②仕入元の照合。
            #   2つを足して1つの数字にしていたので、1段目が残っている間は「4件」と出て
            #   画面には1段目の1件しか出なかった (実測 2026-09-20 19:53 の走行ログ:
            #   「新規/未解決 1件のみ目視」で止まりブラウザを開いている)。
            #   **今出る段の件数だけ**を出す (今日やることの ①→③ と同じ考え方)。
            ("psa_gate", "psa_gate", ("variant_todo|actionable",), None),
            ("restock_build", "restock_build", ("actionable",), "blocked"),
            ("restock_wb", "restock_wb", ("actionable",), None),
            ("offer", "offer_calc", ("actionable",), None)):
        p = d.get(key) or {}
        if p.get("error"):
            err((kind,), p)
        elif p:
            # "a|b" = **先に出る段を優先**し、残っていない時だけ次の段を数える
            n = 0
            for f in fields:
                if "|" in f:
                    for one in f.split("|"):
                        n = _num(p.get(one))
                        if n:
                            break
                else:
                    n += _num(p.get(f))
            hold = _num(p.get(hold_field)) if hold_field else 0
            note = ("止めている %d件" % hold) if hold and not n else ""
            # 1段目が残っている時は、次の段が何件あるかを note に出す (隠したわけではない)
            if kind == "psa_gate" and _num(p.get("variant_todo")) and _num(p.get("actionable")):
                note = (note + " / " if note else "") +                     "答えたら 仕入元の照合 %d件 に進みます" % _num(p.get("actionable"))
            if kind == "sold_restock" and _num(p.get("unknown")):
                note = (note + " / " if note else "") + "判定できない %d件 (押しても動きません)" % _num(p.get("unknown"))
            put(kind, n, n > 0, note, hold)
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
    "watcher": None, "watcher_at": 0,
    "job": None,            # {kind, label, started, rc, running}
    "proc": None,           # 走らせている subprocess (止めるボタン用)
    "stopping": False,      # 止めるボタンで止めた走行か (締めの文言用)
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


BACKUP_STATUS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "review_logs",
                             "data_backup_last.json")
BACKUP_STALE_H = 36


def backup_notice(st, now=None):
    """毎朝の共有データ バックアップ (tools/data_backup.py) の結果 → 知らせ1行 / 問題なければ "" (純関数)。

    ★2026-09-17: SSD 不調でブルースクリーンが続いた日に作った。iMak_data は git 管理外で
      複製がどこにも無かった。**止まっても誰も気づかない**のが一番危ないので、失敗と
      36時間更新なしの両方を出す。
    """
    now = now or datetime.datetime.now()
    if not st:
        return "バックアップ: 結果がありません (data_backup.py が一度も走っていない)"
    if not st.get("ok"):
        return "バックアップ: 失敗 — %s" % (st.get("error") or "理由不明")[:120]
    try:
        at = datetime.datetime.fromisoformat(st.get("at") or "")
    except ValueError:
        return "バックアップ: 結果の時刻が読めません"
    hours = (now - at).total_seconds() / 3600
    if hours > BACKUP_STALE_H:
        return "バックアップ: %d時間 更新されていません (最後 %s)" % (hours, at.strftime("%m/%d %H:%M"))
    return ""


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
                                  "no_price": int(sc.get("no_price", 0) or 0),
                                  "monthly_usd": float(sc.get("monthly_usd", 0.0) or 0),
                                  "monthly": int(sc.get("monthly", 0) or 0)})
        home["month"] = {"usd": m_usd, "count": m_cnt, "shelf_usd": total_usd,
                         "shelf_budget": cp.SHELF_BUDGET_TOTAL_USD}
    except Exception as e:                                     # noqa: BLE001
        home["errors"].append("棚割り: %s" % e)
    try:
        with open(BACKUP_STATUS, encoding="utf-8") as f:
            _bk = json.load(f)
    except Exception:                                          # noqa: BLE001
        _bk = None
    _bn = backup_notice(_bk)
    if _bn:
        home["errors"].append(_bn)
    try:
        home["nightly"] = cp.nightly_last_run() or {}
    except Exception as e:                                     # noqa: BLE001
        home["errors"].append("夜間: %s" % e)
    try:
        home["stats"] = cp._fetch_seller_stats(cp._get_ebay_token()) or {}
        home["stats"]["seller"] = cp.EBAY_SELLER
    except Exception as e:                                     # noqa: BLE001
        home["errors"].append("eBay: %s" % e)
    try:
        home["price_source"] = dict(cp.PRICE_SOURCE)           # 棚割りの金額の出どころ (ファネル)
    except Exception:                                          # noqa: BLE001
        home["price_source"] = {}
    # ファネルが無い = 金額を出せない (シートが読めなかったのとは別物として出す)
    home["price_missing"] = not (home.get("price_source") or {}).get("path")
    home["shelf_unread"] = (not home["price_missing"]) and shelf_looks_unread(home["shelf"])
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
    for i, s in enumerate(cp.SCRIPTS):
        kind = s.get("badge")
        if not kind or kind == "hoju_status":
            continue
        label = display_label(s["label"])
        m = STEP_RE.search(label)
        info = summ.get(kind) or {"n": None, "state": "unknown", "note": "", "hold": 0}
        jobs.append({"kind": kind, "i": i, "label": label, "step": m.group(0) if m else "",
                     "group": group_of(label), "tip": (s.get("tip") or "")[:160],
                     "runnable": runnable(s), "params": s.get("params") or [],
                     "ask_amount": bool(s.get("ask_amount")), **info})
    return {"jobs": jobs, "counts_at": STATE["counts_at"], "counting": STATE["counting"],
            "counts_error": STATE["counts_error"]}


def get_buttons():
    """今の出品くんのボタン一覧 (新規出品の商材カード・各ページの表を、パネルと同じ並びで作る)。"""
    cp = _cp()
    out = []
    for i, s in enumerate(cp.SCRIPTS):
        out.append({"i": i, "type": s.get("type"), "category": s.get("category"),
                    "label": display_label(s["label"]), "badge": s.get("badge"),
                    "runnable": runnable(s), "why": version.why_not_runnable(s),
                    "params": s.get("params") or [], "ask_amount": bool(s.get("ask_amount")),
                    "tip": (s.get("tip") or "")[:160]})
    return {"buttons": out}


def get_version():
    """版と移行状況 (旧パネルの何本が新画面で押せるか / 残りは何が要るか)。"""
    cp = _cp()
    rows, ready = [], 0
    for s in cp.SCRIPTS:
        ok = runnable(s)
        ready += 1 if ok else 0
        rows.append({"label": display_label(s["label"]), "category": s.get("category") or "",
                     "ready": ok, "why": version.why_not_runnable(s)})
    return {"version": version.VERSION, "released": version.RELEASED, "commit": version.git_commit(),
            "total": len(rows), "ready": ready, "rows": rows,
            "changelog": _read_text(os.path.join(HERE, "CHANGELOG.md"))}


def _market_ledger():
    """リサーチの道具 (tools/market_ledger.py) を読み込む。条件セットはあちらが唯一の口。"""
    if TOOLS not in sys.path:
        sys.path.insert(0, TOOLS)
    import market_ledger
    return market_ledger


# ★2026-09-20 ユーザー「よく売れているカードをHTMLで表示して欲しい。何のカードか、
#   何枚売れたか、いくらで売れたか、内が出せているかどうか」。
#   中身は tools/market_ledger.build_cards が唯一の口 (CSV も画面も同じものを見る)。
#   作るのに数秒かかる (シート + カタログ) ので、少しの間 使い回す。
_CARDS = {"at": 0, "v": None}
CARDS_TTL = 180


def research_cards(refresh=False):
    if not refresh and _CARDS["v"] and time.time() - _CARDS["at"] < CARDS_TTL:
        return _CARDS["v"]
    rows, summary = _market_ledger().build_cards()
    out = {"rows": rows, "summary": summary}
    _CARDS["at"], _CARDS["v"] = time.time(), out
    return out


# ★2026-09-20 ユーザー「これだと、開ける前に条件入れないとダメでしょ。開けてから絞り込みたい」。
#   カタログは10万件あって1枚の HTML には収まらないので、画面から ここに聞く形にする。
#   引くのは tools/catalog_browse.fetch が唯一の口。
# ★2026-09-22: カタログの画像がこの PC 内のファイル (ドン!!カード等) の物は、ブラウザから読めず
#   画面に出なかった。カタログの置き場の中だけ、ここから配る (それ以外の場所は配らない)。
CATALOG_IMG_ROOT = os.path.normcase(os.path.normpath(r"C:/dev/iMak_data/catalog"))


def _catalog_img_url(img):
    if img and not img.lower().startswith(("http://", "https://")):
        from urllib.parse import quote
        return "/catalog/img?p=" + quote(img)
    return img


def catalog_img_path(p):
    """配ってよいファイルなら実パス、だめなら None (カタログの置き場の外は配らない)。"""
    path = os.path.normcase(os.path.normpath(p or ""))
    if not path.startswith(CATALOG_IMG_ROOT + os.sep) or not os.path.isfile(path):
        return None
    return path


def catalog_rows(game="", q="", limit=400):
    if TOOLS not in sys.path:
        sys.path.insert(0, TOOLS)
    import sqlite3
    import catalog_browse as CB
    conn = sqlite3.connect(CB.DB)
    out = []
    for pid, name, name_jp, cat, set_name, images, specs in CB.fetch(conn, game, q, limit):
        out.append({"product_id": pid, "name": name, "name_jp": name_jp, "category": cat,
                    "set_name": set_name, "image": _catalog_img_url(CB.first_image(images)),
                    "cert": CB.is_cert_image(CB.first_image(images)),
                    "rarity": CB.spec_of(specs, "rarity"),
                    "no": CB.spec_of(specs, "card_number_text") or pid})
    return {"rows": out, "game": game, "q": q, "limit": limit}


def research_meta():
    """画面に出す選択肢 (商材 / 期間 / 既定)。"""
    m = _market_ledger()
    return {
        "presets": list(m.PRESETS.keys()),
        "ranges": m.DAY_RANGES,
        "default_days": m.DEFAULT_DAYS,
        "ledger": m.LEDGER,
        "rows": len(m.load_ledger()),
    }


# ★2026-09-18: 既定のブラウザ (Edge) で開くと、Terapeak 抜き出しの拡張が入っていないので
#   ボタンが出ない。Chrome を名指しで開く (無ければ既定に落とす)。
CHROME_PATHS = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.join(os.path.expanduser("~"), r"AppData\Local\Google\Chrome\Application\chrome.exe"),
)


def _chrome():
    for p in CHROME_PATHS:
        if os.path.isfile(p):
            return p
    return None


def research_open(preset, tabs, days):
    """条件を焼いた Research の URL を Chrome で開く (SOLD / ACTIVE を選べる)。"""
    m = _market_ledger()
    chrome, urls = _chrome(), []
    # ★検索語は2本 (`PSA10` / `PSA 10`)。片方だけだと空白ありの出品がほぼ全部抜ける (2026-09-21)
    pairs = [(tab, kw) for tab in (tabs or ["SOLD"]) for kw in m.KEYWORDS]
    for tab, kw in pairs:
        url = m.build_url(preset, tab=tab, days=int(days or m.DEFAULT_DAYS), keywords=kw)
        if chrome:
            # ★--new-window: 付けないと「最後に使っていた窓」に入る。Gemini などを
            #   Chrome のアプリとして開いていると、その窓にタブが出てしまう (2026-09-18)
            subprocess.Popen([chrome, "--new-window", url])
        else:
            import webbrowser
            webbrowser.open(url)
        urls.append(url)
    return {"ok": True, "urls": urls, "chrome": bool(chrome)}


def research_run(cmd):
    """ingest / report を走らせて、画面に出す文字を返す。"""
    m = _market_ledger()
    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = (m.cmd_ingest([]) if cmd == "ingest" else m.cmd_report([]))
    return {"ok": code == 0, "text": buf.getvalue(), "rows": len(m.load_ledger())}


def _read_text(path, limit=8000):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()[:limit]
    except OSError:
        return ""


def _tasks_worker():
    # ★2026-09-17: State も取る。Get-ScheduledTaskInfo は **無効化したタスクにも次回時刻を返す**ので、
    #   廃止した DispatchWatch が「前回 失敗 / 次回 09:00」と赤で出ていた (止めてあるだけで異常ではない)。
    ps = ("Get-ScheduledTask | Where-Object { $_.TaskName -like '*iMak*' } | ForEach-Object { "
          "$i = $_ | Get-ScheduledTaskInfo; [pscustomobject]@{ TaskName = $_.TaskName; "
          "State = [string]$_.State; LastRunTime = $i.LastRunTime; LastTaskResult = $i.LastTaskResult; "
          "NextRunTime = $i.NextRunTime } } | ConvertTo-Json -Compress")
    rows = []
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                           capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=90, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        data = json.loads(r.stdout or "[]")
        for t in (data if isinstance(data, list) else [data]):
            disabled = str(t.get("State") or "") == "Disabled"
            rows.append({"name": t.get("TaskName"), "last": _ps_date(t.get("LastRunTime")),
                         "next": "" if disabled else _ps_date(t.get("NextRunTime")),
                         "result": t.get("LastTaskResult"), "disabled": disabled})
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


def _watcher_probe():
    """巡回中のプロセスと、監視くんタスクの次回開始を1回で取る (PowerShell 1回)。"""
    ps = (
        "$p = Get-CimInstance Win32_Process -Filter \"Name like 'python%'\" | "
        "  Where-Object { $_.CommandLine -match 'run_cycle|monitor' } | "
        "  ForEach-Object { @{ cmd = $_.CommandLine; start = $_.CreationDate.ToString('s') } };"
        "$t = Get-ScheduledTask | Where-Object { $_.TaskName -like 'iMakInventory*' } | "
        "  Get-ScheduledTaskInfo | ForEach-Object { @{ name = $_.TaskName; "
        "    next = $(if ($_.NextRunTime) { $_.NextRunTime.ToString('s') } else { '' }) } };"
        "@{ procs = @($p); tasks = @($t) } | ConvertTo-Json -Depth 4 -Compress"
    )
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=90, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return json.loads(r.stdout or "{}")


def _watcher_worker():
    now = datetime.datetime.now()
    try:
        d = _watcher_probe()
        running = {}
        for p in (d.get("procs") or []):
            task = watcher.task_of_cmdline(p.get("cmd"))
            st = watcher._parse(p.get("start"))
            if task and st:
                running[task] = st
        nexts = {}
        for t in (d.get("tasks") or []):
            if t.get("name") in watcher.TASKS:
                nexts[t["name"]] = watcher._parse(t.get("next"))
        runs = watcher.update_runs(watcher.load_runs(), running, now)
        watcher.save_runs(runs)
        rows = watcher.status(runs, running, nexts, now)
        STATE["watcher"] = {"rows": rows, "line": watcher.headline(rows, now),
                            "at": now.strftime("%H:%M")}
    except Exception as e:                                     # noqa: BLE001
        STATE["watcher"] = {"rows": [], "line": "巡回の状況が取れません (%s)" % e, "at": ""}
    STATE["watcher_at"] = time.time()


def get_watcher():
    """監視くんの巡回 (巡回中か / 終了めやす / 次回)。記録は _watcher_loop が2分ごとに回す。"""
    if STATE["watcher"] is None and time.time() - STATE["watcher_at"] > 30:
        STATE["watcher_at"] = time.time()
        threading.Thread(target=_watcher_worker, daemon=True).start()
    return STATE["watcher"] or {"rows": [], "line": "読込中…", "loading": True}


def _watcher_loop():
    """画面を閉じていても巡回を記録し続ける (2分ごと)。

    ★画面のポーリング任せにすると、窓を閉じている間の巡回が記録されず、
      「1回だいたい何分か」がいつまでも出ない。
    """
    while True:
        try:
            _watcher_worker()
        except Exception:                                      # noqa: BLE001
            pass
        time.sleep(120)


def get_tasks():
    if STATE["tasks"] is None or time.time() - STATE["tasks_at"] > TASKS_TTL:
        STATE["tasks_at"] = time.time()
        threading.Thread(target=_tasks_worker, daemon=True).start()
    return STATE["tasks"] or {"tasks": [], "loading": True}


def find_script(kind=None, index=None):
    """badge (kind) か 並び順 (index) でボタンを1つ選ぶ。新規出品は badge を持たないので index で押す。"""
    cp = _cp()
    if index is not None:
        try:
            index = int(index)
        except (TypeError, ValueError):
            return None
        if 0 <= index < len(cp.SCRIPTS):
            return cp.SCRIPTS[index]
        return None
    if kind:
        return next((s for s in cp.SCRIPTS if s.get("badge") == kind), None)
    return None


def build_cmd(script, params=None, amount=None):
    """旧パネルの run_script と同じ組み立て (入力欄 → --name 値 / 金額 → --amount)。"""
    cmd = list(script["cmd"])
    if script.get("ask_amount"):
        v = str(amount or "").strip().replace(",", "").replace("$", "")
        if v:
            float(v)                                   # 読めない文字は呼び出し側に返す
            cmd.extend(["--amount", v])
    for p in (script.get("params") or []):
        v = str((params or {}).get(p["name"], "") or "").strip()
        if v:
            cmd.extend([p["name"], v])
    return cmd


def run_job(kind=None, index=None, params=None, amount=None):
    script = find_script(kind, index)
    if not script:
        return 404, {"error": "そのボタンはありません"}
    if not runnable(script):
        return 409, {"error": "このボタンはウィザード画面が要るので、今の出品くんで押してください"}
    try:
        cmd = build_cmd(script, params, amount)
    except ValueError:
        return 400, {"error": "金額として読めません: %s" % amount}
    with _LOCK:
        if STATE["job"] and STATE["job"].get("running"):
            return 409, {"error": "「%s」が実行中です。終わってから押してください" % STATE["job"]["label"]}
        STATE["job"] = {"kind": kind or script.get("badge") or "", "label": display_label(script["label"]),
                        "started": datetime.datetime.now().strftime("%H:%M:%S"), "rc": None, "running": True}
    threading.Thread(target=_run_worker, args=(script, cmd), daemon=True).start()
    return 200, {"ok": True}


# 出品くんが動かす道具 (前のサーバが残した走行を見つける手掛かり)
ORPHAN_HINTS = ("psa_to_csv.py", "tshirt_listing.py", "gshock_to_csv.py", "psa_hoju_fill.py",
                "ut_hoju_fill.py", "ut_identify.py", "ichibankuji_restock.py", "sold_restock.py",
                "cull_end.py", "shelf_evict.py", "newcand_confirm.py", "psa_restock_build.py",
                "psa_resource_gate.py", "mercari_to_ebay_csv.py", "workman_listing.py",
                "montbell_listing.py", "csv_auditor.py")


def find_orphan_run():
    """前のサーバが残した走行 (pid, 何を動かしているか)。無ければ None。"""
    if sys.platform != "win32":
        return None
    ps = ("Get-CimInstance Win32_Process -Filter \"Name like 'python%'\" | "
          "Select-Object ProcessId,CommandLine,@{n='at';e={$_.CreationDate.ToString('s')}} | ConvertTo-Json -Compress")
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                           capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=60, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        data = json.loads(r.stdout or "[]")
    except Exception:                                          # noqa: BLE001
        return None
    for p in (data if isinstance(data, list) else [data]):
        cl = str((p or {}).get("CommandLine") or "")
        if "console" in cl.replace("\\", "/"):               # Console 自身は除く
            continue
        for hint in ORPHAN_HINTS:
            if hint in cl:
                return {"pid": int(p.get("ProcessId")), "what": hint,
                        "at": str(p.get("at") or "")[11:19]}
    return None


def adopt_orphan_run():
    """前の走行を拾って「実行中」として扱う (止めるボタンを効かせるため)。"""
    o = find_orphan_run()
    if not o:
        return
    with _LOCK:
        if STATE["job"] and STATE["job"].get("running"):
            return
        STATE["job"] = {"kind": "", "label": "%s (前のサーバの走行)" % o["what"],
                        "started": o["at"], "rc": None, "running": True, "orphan_pid": o["pid"]}
    _log("↻ 前のサーバが残した走行を見つけました: %s (pid %s)。止めるボタンで止められます"
         % (o["what"], o["pid"]))


def stop_job():
    """走っている処理を止める (旧パネルの「停止」と同じ止め方 = 子プロセスごと)。"""
    with _LOCK:
        job = dict(STATE["job"]) if STATE["job"] else None
        p = STATE["proc"]
    if not job or not job.get("running"):
        return 409, {"error": "今は何も走っていません"}
    _log("■ 止めます: %s" % job.get("label", ""))
    STATE["stopping"] = True
    if p is None:                                              # 前のサーバの走行 (pid だけ分かる)
        pid = job.get("orphan_pid")
        if not pid:
            return 409, {"error": "止め方が分かりません (前のサーバの走行で pid 不明)"}
        try:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True,
                           timeout=60, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except Exception as e:                                 # noqa: BLE001
            return 500, {"error": "止められませんでした: %s" % e}
        with _LOCK:
            STATE["job"].update(rc=None, running=False)
            STATE["stopping"] = False
        _log("■ 止めました (前のサーバの走行)")
        return 200, {"ok": True}
    try:
        _cp()._kill_process_tree(p, _log)                      # control_panel と同じ関数を使う
    except Exception as e:                                     # noqa: BLE001
        return 500, {"error": "止められませんでした: %s" % e}
    return 200, {"ok": True}


def count_of(kind):
    """今の件数 (種類ごと)。数えていなければ None。"""
    if not kind or not STATE.get("counts"):
        return None
    info = summarize(STATE["counts"]).get(kind)
    return info.get("n") if info else None


def _run_worker(script, cmd=None):
    """走る前のガード → 実行 → 後処理。**旧パネルと同じ関数** (control_panel.before_run / after_run)。"""
    cp = _cp()
    label = display_label(script["label"])
    cmd = list(cmd or script["cmd"])
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1", **(script.get("env") or {}))
    _log("▶ %s  (%s)" % (label, " ".join(cmd)))
    fh = path = None
    try:
        fh, path = cp._open_run_log(script["label"])
        fh.write("=== %s (%s) console ===\ncwd: %s\ncmd: %s\n\n" % (
            script["label"], time.strftime("%Y-%m-%d %H:%M:%S"), script["cwd"], " ".join(cmd)))
        _log("  記録: %s" % path)
    except Exception:                                          # noqa: BLE001
        fh = path = None

    def _to_log(text):
        """後処理のログは **画面だけ** に出す (run log ファイルには書かない)。

        ★ここを「記録にも書く」にすると旧パネルと動きが変わる: 後処理は run log を
          「今回の stdout」として読み直すので、後処理自身が書いた文 (問題提起の引用など) が
          次の段の入力に混ざり、NO-GO 行を二重に拾う。旧パネルは画面にしか出していない。
        """
        _log(text)

    def _run_log_text():
        """今回の走行の stdout (旧パネルの _run_log_text と同じ: run log ファイルから読む)。"""
        if not path:
            return ""
        try:
            if fh and not fh.closed:
                fh.flush()
            with open(path, encoding="utf-8", errors="replace") as f:
                return f.read()
        except OSError:
            return ""

    started = None
    rc = None
    before = count_of(script.get("badge"))        # 押す前の件数 (走行後に減ったか見る)
    try:
        if not cp.before_run(script, _to_log):                  # 新規生成の安全弁 (N列関数ガード等)
            _log("🚫 走る前の確認で中止しました")
            with _LOCK:
                STATE["job"].update(rc=None, running=False)
            return
        started = time.time()      # 旧パネルと同じ位置 (今回の CSV だけを後処理の対象にする基準)
        # ★2026-09-16: サーバを入れ替えた時に **走行中の作業を道連れにしない**。
        #   実害: 18:11 にサーバを再起動して、走っていた 🤖自動 (PSA) を落とした。
        #   別のプロセスグループで起こす (止めるボタンは今までどおりツリーごと止める)。
        _flags = (getattr(subprocess, "CREATE_NO_WINDOW", 0)
                  | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                  | getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0))
        p = subprocess.Popen(cmd, cwd=script["cwd"], env=env,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                             encoding="utf-8", errors="replace", bufsize=1,
                             creationflags=_flags)
        STATE["proc"] = p                                      # 止めるボタン用
        for line in p.stdout:
            _log(line)
            if fh:
                fh.write(line)
                fh.flush()
        rc = p.wait()
    except Exception as e:                                     # noqa: BLE001
        _log("起動できませんでした: %s" % e)
    _log("--- 終了 (returncode=%s) ---" % rc)
    try:
        cp.after_run(script, rc, _to_log, run_log_text=_run_log_text, listing_start_ts=started)
    except Exception as e:                                     # noqa: BLE001
        _log("⚠️ 後処理で例外: %s" % e)
    finally:
        if fh and not fh.closed:
            fh.close()
    if STATE.get("stopping"):
        _log("■ 止めました (途中で終了しました)")
    with _LOCK:
        STATE["job"].update(rc=rc, running=False)
        STATE["proc"] = None
        stopped = STATE["stopping"]
        STATE["stopping"] = False
    refresh_counts()
    # ★押したのに件数が減らなかったら、その場で言う (旧パネルと同じ判定を使う)。
    #   失敗した走行・止めた走行は何もしていないので突き合わせない。
    if rc in (0, None) and not stopped:
        badge = script.get("badge")
        after = count_of(badge)
        try:
            if badge and badge not in SEARCH_KINDS and cp.badge_did_not_move(before, after):
                _log("⚠️ 押しても件数が減りませんでした (%s: %s件 → %s件)。"
                     "表示が『作業できる件数』になっていない可能性があります"
                     % (label, before, after))
                cp._record_badge_drift(badge, label, before, after)
        except Exception:                                      # noqa: BLE001
            pass


# ---------------------------------------------------------------- HTTP

_TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
          ".js": "application/javascript; charset=utf-8", ".svg": "image/svg+xml",
          ".png": "image/png", ".ico": "image/x-icon", ".jpg": "image/jpeg",
          ".jpeg": "image/jpeg", ".webp": "image/webp"}


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
        if u.path == "/api/watcher":
            return self._json(200, get_watcher())
        if u.path == "/api/version":
            return self._json(200, get_version())
        if u.path == "/api/research":
            try:
                return self._json(200, research_meta())
            except Exception as e:                       # noqa: BLE001 画面に出して知らせる
                return self._json(200, {"error": str(e)})
        if u.path == "/api/catalog":
            try:
                p = parse_qs(u.query)
                return self._json(200, catalog_rows(
                    (p.get("game") or [""])[0], (p.get("q") or [""])[0],
                    min(int((p.get("limit") or ["400"])[0] or 400), 2000)))
            except Exception as e:                       # noqa: BLE001 画面に出して知らせる
                return self._json(200, {"error": str(e)})
        if u.path == "/catalog/img":
            path = catalog_img_path((parse_qs(u.query).get("p") or [""])[0])
            if not path:
                return self._json(404, {"error": "not found"})
            with open(path, "rb") as f:
                b = f.read()
            self.send_response(200)
            self.send_header("Content-Type", _TYPES.get(os.path.splitext(path)[1].lower(), "application/octet-stream"))
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            return self.wfile.write(b)
        if u.path == "/catalog":
            # 画面もここから配る。file:/// で開くとブラウザが問い合わせを止める (同じ出所に揃える)
            import catalog_browse as CB
            b = CB.page(api="/api/catalog").encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            return self.wfile.write(b)
        if u.path == "/api/research/cards":
            try:
                q = parse_qs(u.query)
                return self._json(200, research_cards(refresh=bool(q.get("refresh"))))
            except Exception as e:                       # noqa: BLE001 画面に出して知らせる
                return self._json(200, {"error": str(e)})
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
            code, obj = run_job(kind=str(body.get("kind") or "") or None,
                                index=body.get("i"), params=body.get("params"),
                                amount=body.get("amount"))
            return self._json(code, obj)
        if u.path == "/api/stop":
            code, obj = stop_job()
            return self._json(code, obj)
        if u.path == "/api/research/open":
            try:
                return self._json(200, research_open(body.get("preset"), body.get("tabs"),
                                                     body.get("days")))
            except Exception as e:                       # noqa: BLE001
                return self._json(200, {"ok": False, "error": str(e)})
        if u.path == "/api/research/run":
            try:
                return self._json(200, research_run(str(body.get("cmd") or "report")))
            except Exception as e:                       # noqa: BLE001
                return self._json(200, {"ok": False, "error": str(e)})
        if u.path == "/api/refresh":
            threading.Thread(target=refresh_counts, daemon=True).start()
            STATE["crew_at"] = 0                     # ホームは数え終わってから読む (refresh_counts)
            return self._json(200, {"ok": True})
        return self._json(404, {"error": "not found"})


def _port_in_use(port):
    with socket.socket() as s:
        return s.connect_ex((HOST, port)) == 0


WINDOW_TITLE = "出品くん Console"          # index.html の <title> と同じ


def _console_windows():
    """既に開いている「出品くん Console」の窓 (Windows 以外・失敗時は空)。

    ★Edge のアプリ窓は既存の msedge プロセスに相乗りするため、プロセス一覧では見つからない
      (コマンドラインに URL が残らない)。窓の題名で探す。
    """
    if sys.platform != "win32":
        return []
    try:
        import ctypes
        user32 = ctypes.windll.user32
        found = []
        proc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

        def _cb(hwnd, _lparam):
            if user32.IsWindowVisible(hwnd):
                n = user32.GetWindowTextLengthW(hwnd)
                if n:
                    buf = ctypes.create_unicode_buffer(n + 1)
                    user32.GetWindowTextW(hwnd, buf, n + 1)
                    if WINDOW_TITLE in buf.value:
                        found.append(hwnd)
            return True

        user32.EnumWindows(proc(_cb), 0)
        return found
    except Exception:                                          # noqa: BLE001
        return []


def open_window():
    """窓を開く。既に開いていれば **前に出すだけ** (二重に開かない)。"""
    wins = _console_windows()
    if wins:
        try:
            import ctypes
            ctypes.windll.user32.ShowWindow(wins[0], 9)        # 9 = SW_RESTORE
            ctypes.windll.user32.SetForegroundWindow(wins[0])
            return
        except Exception:                                      # noqa: BLE001
            return                                             # 前に出せなくても二重には開かない
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
    threading.Thread(target=_watcher_loop, daemon=True).start()
    threading.Thread(target=adopt_orphan_run, daemon=True).start()
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    if "--no-open" not in sys.argv:
        threading.Timer(0.6, open_window).start()
    srv.serve_forever()


if __name__ == "__main__":
    main()
