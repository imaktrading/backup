# -*- coding: utf-8 -*-
"""秘書くん — 今日やることを **定量根拠つき** で最大N件出す (2026-08-01)。

なぜ作るか:
    出品/監査/依頼/発送/仕入れ の信号は既に全部あるが、**バラバラの場所にあって
    「今日どれからやるか」が人の頭の中にしか無い**。毎朝それを組み直すのは無駄で、
    しかも期限もの (発送遅延=Defect) を取りこぼすと売上より先に account health が削れる。

設計方針:
    - **推測しない**。数字は実データ (eBay API / 管理スプシ / pdca.db / schtasks) からのみ。
      取得できなかった source は「取得不可」と明示する (黙って0件にしない = fail-OPEN 防止)。
    - **出しすぎない**。全部並べると digest と同じで読まれなくなるので既定 5 件。
      閾値未満のプールは出さない。
    - 判定ロジックは純関数に寄せて test 可能にする (I/O は collector 側)。

出力:
    コンソール + `review_logs/today_brief_<date>.md`
使い方:
    python today_brief.py                # 今日のブリーフ
    python today_brief.py --limit 8      # 件数変更
    python today_brief.py --target 150000
    python today_brief.py --json         # 機械可読
"""
from __future__ import annotations

import argparse
import calendar
import collections
import datetime
import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request

_HERE = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.normpath(os.path.join(_HERE, "..", ".."))
REVIEW_DIR = os.path.join(WORKSPACE, "iMakHQ", "review_logs")
EBAY_DIR = os.path.join(WORKSPACE, "iMakeBayAPI")
PDCA_DB = r"C:/dev/iMak_data/audit/pdca.db"
REQUESTS_ROOT = r"C:/dev/iMak_data"

TARGET_JPY_DEFAULT = 100_000          # 月商目標 (ユーザー設定 2026-08-01)

# 統合管理シート (HIGH/LOW の両方を見ないと live 在庫の半分を見落とす。
# 2026-08-01 初版は HIGH だけ見て「live 380件・TCG に67%偏り」と誤報告した。
# 実際は 777件で G-shock 259 / TCG 252 = ほぼ半々だった)
CONSOLIDATED_SHEETS = {
    "HIGH": ("19kj8NqWHIGP1ptQDeGePw077hpdl6dNOO-v2J10HCjk", 851100680),
    "LOW": ("1jF9vggbfUCddjneROMO2GGN-jTAPRbq6Qe2cbgr37B0", 851100680),
}

# 1日にこなす量 (指示を「全部やれ」にしない。毎日ここだけ削れば必ず減る量)
DAILY_HOJU_CHECK = 10                 # 補URL 目視確認 (1件30秒)
DAILY_PRICE_REVIEW = 3                # 高閲覧・未成約の値下げ/追加出品 判断
MIN_PER_HOJU = 0.5
MIN_PER_PRICE = 5.0
MIN_PER_LISTING = 4.0                 # 1件出品するのにかかる実測見込み

# 閾値: これ未満のプールは「溜まっている」と言わない (ノイズ抑制)
TH_HOJU_ZERO = 20                     # 補URL 0本の live PSA
TH_POOL = 30                          # 汎用の作業プール
TH_VIEWS_NO_SALE = 30                 # 30日で見られているのに売れていない
TH_CATEGORY_SKEW = 0.60               # 1カテゴリが live の何割を超えたら偏りとみなすか

PRI_ORDER = {"P0": 0, "P1": 1, "P2": 2}


# =========================================================================
# 純関数 (テスト対象)
# =========================================================================

def month_pace(sold_jpy, today, target_jpy):
    """月商目標に対する進捗と、残日数から要求される1日あたりの必要額。

    Returns: dict(elapsed, days_in_month, remaining_days, sold, target, expected,
                  gap, need_per_day, on_track)
    expected = 目標 × 経過日数/月日数 (等ペース前提)。gap>0 なら遅れ。
    """
    dim = calendar.monthrange(today.year, today.month)[1]
    elapsed = today.day
    remaining = max(0, dim - elapsed)
    expected = target_jpy * elapsed / dim
    gap = expected - sold_jpy
    need_per_day = (target_jpy - sold_jpy) / remaining if remaining else 0.0
    return {"elapsed": elapsed, "days_in_month": dim, "remaining_days": remaining,
            "sold": sold_jpy, "target": target_jpy, "expected": expected,
            "gap": gap, "need_per_day": need_per_day, "on_track": gap <= 0}


def days_left(due_date, today):
    """期限までの残日数 (期限切れは負)。パース不能は None。"""
    if not due_date:
        return None
    try:
        d = datetime.date.fromisoformat(str(due_date)[:10])
    except Exception:
        return None
    return (d - today).days


def urgency_score(item):
    """並べ替え用スコア。小さいほど先。優先度 → 期限の近さ → 件数の多い順。"""
    pri = PRI_ORDER.get(item.get("pri", "P2"), 9)
    dl = item.get("days_left")
    dl = 999 if dl is None else dl
    return (pri, dl, -int(item.get("count") or 0))


def rank(items, limit):
    return sorted(items, key=urgency_score)[:limit]


def category_skew(counts):
    """カテゴリ別 live 件数 → (最大カテゴリ, 割合, 手薄カテゴリ一覧)。

    counts が空なら (None, 0.0, [])。割合は最大カテゴリ / 全体。
    """
    total = sum(counts.values())
    if not total:
        return None, 0.0, []
    top, n = max(counts.items(), key=lambda kv: kv[1])
    thin = [k for k, v in sorted(counts.items(), key=lambda kv: kv[1]) if v < total * 0.1]
    return top, n / total, thin


# ★指示は「押すボタン」まで落とす。文章で手順を書いても人は動けない (2026-08-01 ユーザー指摘)。
#   値は control_panel.SCRIPTS の label と **完全一致**させること (パネル側が label で引く)。
#   ここに無い作業は url= で開き先を持たせる。
BTN_HOJU = "🩹 補URL補強(昼確認/slice3)"
BTN_END = "取下再出品① 取下げ(End)"
BTN_PRICE = "💲 価格見直し"
BTN_RESTOCK = "🛒 在庫切れ再仕入れ"
URL_ORDERS = "https://www.ebay.com/sh/ord?filter=status%3AAWAITING_SHIPMENT"


def make_item(pri, title, why, action, source, count=None, days_left_=None,
              how="", effect="", minutes=None, button="", url=""):
    """title は **今日の指示** (「〜を N 件やる」)。事実だけ書かない。

    why=数字の根拠 / how=どのボタン・コマンドか / effect=やると何が変わるか /
    minutes=所要見込み。人が「で、何をすればいい?」と聞き返さなくて済む形にする。
    """
    return {"pri": pri, "title": title, "why": why, "action": action,
            "source": source, "count": count, "days_left": days_left_,
            "how": how, "effect": effect, "minutes": minutes,
            "button": button, "url": url}


def sales_econ(sold_rows, target_jpy):
    """成約実績から「目標に何件必要か」を出す (純関数)。

    sold_rows: [(month 'YYYY-MM', jpy)] の list (返金除外済)。
    Returns: dict(n, avg, median, by_month, need_sales, months_ok, months_ng) / 実績0なら None。
    ★目標達成の判断は **月商の実績** で見る。当月途中の累計だけ見て「遅れ」と言うと、
      月初は必ず遅れ判定になって毎朝ノイズになる (初版の失敗)。
    """
    if not sold_rows:
        return None
    vals = sorted(v for _, v in sold_rows)
    by_month = collections.Counter()
    cnt_month = collections.Counter()
    for m, v in sold_rows:
        by_month[m] += v
        cnt_month[m] += 1
    avg = sum(vals) / len(vals)
    med = vals[len(vals) // 2]
    return {"n": len(vals), "avg": avg, "median": med,
            "by_month": dict(by_month), "cnt_month": dict(cnt_month),
            "need_sales": target_jpy / avg if avg else 0,
            "months_ok": sorted(m for m, v in by_month.items() if v >= target_jpy),
            "months_ng": sorted(m for m, v in by_month.items() if v < target_jpy)}


def stale_view_cutoff(traffic_rows):
    """トラフィック API は 200件しか返さない (offset 無効)。

    そのため「載っていない = 閲覧0」とは断定できない。**最下位の閲覧数**を返し、
    「これ以下」としか言わないことで fail-OPEN (0と断定して切り捨てる) を避ける。
    """
    if not traffic_rows:
        return None
    return min(r[2] for r in traffic_rows)


# =========================================================================
# collector (I/O。1つ落ちても全体は落とさない。失敗は errors に積む)
# =========================================================================

def _ebay_token():
    with open(os.path.join(EBAY_DIR, "ebay_oauth_token_sell.json"), encoding="utf-8") as f:
        return json.load(f)["access_token"]


def _ebay_get(path, query, token, timeout=60):
    url = f"https://api.ebay.com{path}?" + urllib.parse.urlencode(query)
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + token,
                                               "Accept": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=timeout))


def _refresh_token():
    """access_token は 2h で切れる。401 の時だけ更新する (毎回叩かない)。"""
    subprocess.run([sys.executable, "oauth_sell_setup.py", "refresh"],
                   cwd=EBAY_DIR, capture_output=True, timeout=120)


def collect_orders(today, errors):
    """未発送注文 + 今月の成約額 + 90日の成約明細。

    Returns: (unshipped[], 当月 sold_jpy, [(YYYY-MM, jpy)])
    ★90日分を取るのは「平均成約単価」を出すため。目標¥100,000 を件数に翻訳できないと
      「今日何をすればいいか」に落ちない (2026-08-01 ユーザー指摘)。
    """
    try:
        import importlib
        sys.path.insert(0, EBAY_DIR)
        pp = importlib.import_module("profit_params")
    except Exception as e:
        errors.append(f"為替 SSOT 読込不可: {type(e).__name__}")
        pp = None

    def fx(cur):
        if not pp:
            return None
        try:
            return float(pp.get_exchange_rate(cur))
        except Exception:
            return None

    since = (datetime.datetime.utcnow() - datetime.timedelta(days=90)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    q = {"filter": f"creationdate:[{since}..]", "limit": "200"}
    try:
        tok = _ebay_token()
        try:
            d = _ebay_get("/sell/fulfillment/v1/order", q, tok)
        except urllib.error.HTTPError as he:
            if he.code != 401:
                raise
            _refresh_token()
            d = _ebay_get("/sell/fulfillment/v1/order", q, _ebay_token())
    except Exception as e:
        errors.append(f"eBay 注文 取得不可: {type(e).__name__}: {str(e)[:80]}")
        return [], None, []

    unshipped, sold_jpy, sold_rows = [], 0.0, []
    for o in d.get("orders", []):
        pay = o.get("orderPaymentStatus")
        if pay in ("FULLY_REFUNDED", "FAILED"):
            continue                                   # 返金済 = 売上でも作業でもない
        li = (o.get("lineItems") or [{}])[0]
        tot = (o.get("pricingSummary", {}).get("total") or {})
        cur, val = tot.get("currency", "USD"), float(tot.get("value") or 0)
        rate = fx(cur) or fx("USD")
        jpy = val * rate if rate else 0.0
        cd = (o.get("creationDate") or "")[:10]
        if jpy:
            sold_rows.append((cd[:7], jpy))
        if cd[:7] == today.strftime("%Y-%m"):
            sold_jpy += jpy
        if o.get("orderFulfillmentStatus") != "FULFILLED" and pay == "PAID":
            inst = (li.get("lineItemFulfillmentInstructions") or {})
            unshipped.append({"date": cd, "title": (li.get("title") or "")[:60],
                              "amount": f"{cur} {val:.2f}", "jpy": jpy,
                              "ship_by": (inst.get("shipByDate") or "")[:10]})
    return unshipped, sold_jpy, sold_rows


def collect_traffic(errors, days=30):
    """出品ごとの閲覧数 (30日)。Returns: (total_views, [(item_id, impressions, views, tx)])"""
    end = datetime.date.today()
    start = end - datetime.timedelta(days=days)
    q = {"dimension": "LISTING",
         "filter": f"marketplace_ids:{{EBAY_US}},date_range:[{start:%Y%m%d}..{end:%Y%m%d}]",
         "metric": "LISTING_IMPRESSION_TOTAL,LISTING_VIEWS_TOTAL,TRANSACTION",
         "sort": "-LISTING_VIEWS_TOTAL", "limit": "200"}
    try:
        tok = _ebay_token()
        try:
            d = _ebay_get("/sell/analytics/v1/traffic_report", q, tok)
        except urllib.error.HTTPError as he:
            if he.code != 401:
                raise
            _refresh_token()
            d = _ebay_get("/sell/analytics/v1/traffic_report", q, _ebay_token())
    except Exception as e:
        errors.append(f"eBay トラフィック 取得不可: {type(e).__name__}: {str(e)[:80]}")
        return _traffic_from_cache(errors)
    rows = []
    for r in d.get("records", []):
        dim = [v.get("value") for v in r.get("dimensionValues", [])]
        met = [v.get("value") for v in r.get("metricValues", [])]
        if not dim or len(met) < 3:
            continue
        rows.append((dim[0], int(met[0] or 0), int(met[1] or 0), int(met[2] or 0)))
    if not rows:
        # ★eBay Analytics は **例外ではなく空 records** を返すことがある (2026-08-01 実測、断続的)。
        #   これを「閲覧0件」として扱うと、売上に一番近い提案 (高閲覧・未成約 / 死に筋入替) が
        #   毎回 静かに消える = fail-OPEN。空は「不明」として扱い、前回値で埋める。
        errors.append("eBay トラフィックが空で返った (API 側の断続的な挙動)")
        return _traffic_from_cache(errors)
    _traffic_save(rows)
    return sum(r[2] for r in rows), rows


_TRAFFIC_CACHE = os.path.join(REVIEW_DIR, "traffic_cache.json")


def _traffic_save(rows):
    try:
        os.makedirs(REVIEW_DIR, exist_ok=True)
        with open(_TRAFFIC_CACHE, "w", encoding="utf-8") as f:
            json.dump({"ts": datetime.datetime.now().isoformat(timespec="minutes"),
                       "rows": rows}, f)
    except Exception:
        pass


def _traffic_from_cache(errors):
    """前回成功時のトラフィックで代替する (日付を明示して使う)。"""
    try:
        with open(_TRAFFIC_CACHE, encoding="utf-8") as f:
            d = json.load(f)
        rows = [tuple(r) for r in d.get("rows", [])]
        if rows:
            errors.append(f"→ {d.get('ts','?')} 時点のキャッシュで代替 ({len(rows)}件)")
            return sum(r[2] for r in rows), rows
    except Exception:
        pass
    errors.append("→ キャッシュも無いため、閲覧に基づく提案は今回スキップ (0件ではなく不明)")
    return 0, []


def collect_sheet(errors):
    """管理スプシ: live 件数 / カテゴリ内訳 / 出品ペース / 補URL 滞留。"""
    out = {"live": 0, "by_category": collections.Counter(), "listed_recent": {},
           "hoju": None, "sold_ids": set(), "live_meta": {}}
    listed = collections.Counter()
    high_vals = None
    for name, (sid, gid) in CONSOLIDATED_SHEETS.items():
        try:
            import gspread
            from google.oauth2.service_account import Credentials
            sys.path.insert(0, _HERE)
            import sheet_io
            creds = Credentials.from_service_account_file(
                sheet_io.CREDS_PATH, scopes=["https://www.googleapis.com/auth/spreadsheets"])
            vals = gspread.authorize(creds).open_by_key(sid).get_worksheet_by_id(gid).get_all_values()
        except Exception as e:
            errors.append(f"管理スプシ {name} 取得不可: {type(e).__name__}: {str(e)[:60]}")
            continue
        if name == "HIGH":
            high_vals = vals
        hdr = {h: i for i, h in enumerate(vals[0])}
        need = ("itemID", "売り切れ", "カテゴリ")
        if not all(k in hdr for k in need):
            errors.append(f"管理スプシ {name}: 想定列が無い (列構成が変わった可能性)")
            continue
        for r in vals[1:]:
            if len(r) <= max(hdr[k] for k in need):
                continue
            item = r[hdr["itemID"]].strip()
            if not item:
                continue
            if r[hdr["売り切れ"]].strip():
                out["sold_ids"].add(item)
                continue
            if item in out["live_meta"]:
                continue          # HIGH/LOW に同じ itemID が両方載る (実測 42件)。二重計上しない
            out["live"] += 1
            cat = r[hdr["カテゴリ"]].strip() or "(未分類)"
            out["by_category"][cat] += 1
            # 表示名は **`タイトル`(和文) を優先**。PSA 行は `Title` 列に cert 番号が入っており
            # そちらを使うと「138056961」のような数字が並んで人が読めない (2026-08-01 実測)。
            nm = ""
            for key in ("タイトル", "Title"):
                i = hdr.get(key)
                if i is not None and i < len(r) and r[i].strip():
                    nm = r[i].strip()
                    break
            out["live_meta"][item] = (nm, cat)
            di = hdr.get("出品日時")
            d = r[di][:10] if di is not None and di < len(r) else ""
            if d:
                listed[d] += 1
    out["listed_recent"] = dict(sorted(listed.items())[-14:])
    if high_vals:
        try:
            sys.path.insert(0, _HERE)
            import psa_hoju_fill as ph
            out["hoju"] = ph.backfill_status(high_vals)
        except Exception as e:
            errors.append(f"補URL 状況 取得不可: {type(e).__name__}")
    return out


def collect_blockers(errors):
    """詰まりの定量化: 要返球 / pdca 滞留 / 定期タスク異常。"""
    out = {"requests": [], "pdca_pending": None, "pdca_oldest_days": None, "tasks": []}
    # 1) 各 worktree の未処理依頼。判定は **worktree_board の SSOT を再利用**
    #    (ここで独自に「終端語なし」を書くと決着済みの古い依頼まで拾って 148件 のような
    #     偽の山ができる。2026-08-01 初版で実際にそうなった)
    try:
        sys.path.insert(0, _HERE)
        import worktree_board as wb
        for target in ("hq", "catalog", "dedupe", "inventory", "harvest", "revise"):
            mine, theirs, drafts = wb.pending_for(target)
            if mine or drafts:
                latest = max(mine + drafts, key=lambda p: p.stat().st_mtime).name
                out["requests"].append((target, len(mine) + len(drafts), latest))
    except Exception as e:
        errors.append(f"依頼ボード 取得不可: {type(e).__name__}: {str(e)[:60]}")
    # 2) pdca queue の滞留
    try:
        import sqlite3
        con = sqlite3.connect(PDCA_DB)
        row = con.execute("SELECT COUNT(*), MIN(created_ts) FROM improvement_queue"
                          " WHERE status='pending'").fetchone()
        out["pdca_pending"] = row[0]
        if row[1]:
            out["pdca_oldest_days"] = days_left(row[1], datetime.date.today())
            out["pdca_oldest_days"] = -out["pdca_oldest_days"] if out["pdca_oldest_days"] is not None else None
        con.close()
    except Exception as e:
        errors.append(f"pdca.db 取得不可: {type(e).__name__}")
    # 3) 定期タスクの異常終了 (0 / 267009=実行中 / 267014=再起動構成 は正常)
    try:
        ps = ("Get-ScheduledTask | Where-Object {$_.TaskName -like '*iMak*'} | Get-ScheduledTaskInfo |"
              " Select-Object TaskName,LastTaskResult | ConvertTo-Json -Compress")
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                           capture_output=True, text=True, timeout=90)
        for t in json.loads(r.stdout or "[]"):
            if t.get("LastTaskResult") not in (0, 267009, 267014):
                out["tasks"].append((t.get("TaskName"), t.get("LastTaskResult")))
    except Exception as e:
        errors.append(f"定期タスク 取得不可: {type(e).__name__}")
    return out


# =========================================================================
# 提案の組み立て (収集済みデータ → item[]。ここも極力純関数)
# =========================================================================

def build_items(today, orders, sold_jpy, traffic_rows, sheet, blockers, pace, econ=None):
    """★出すのは「事実」ではなく **今日の指示**。

    各項目は「何を・何件・どうやって」まで落とす。事実だけ並べると
    「で、何をすればいい?」が残る (2026-08-01 ユーザー指摘)。
    """
    items = []
    meta = sheet.get("live_meta") or {}
    live = sheet.get("live", 0)

    # --- P0: 期限もの (落とすと Defect) ---
    for o in orders:
        dl = days_left(o["ship_by"], today)
        items.append(make_item(
            "P0", f"仕入れて発送する: {o['title'][:40]}",
            f"{o['date']} 注文 / {o['amount']} 入金済 / 発送期限 {o['ship_by']}"
            + (f" = 残 {dl} 日" if dl is not None else ""),
            "仕入れ → 発送",
            "eBay Fulfillment API", days_left_=dl, minutes=30, url=URL_ORDERS,
            how="Seller Hub の Awaiting shipment を開く → 仕入元を確定して購入 → 発送登録",
            effect="期限超過は Late shipment = Defect。1件でも account health が削れる"))

    # --- P1: 需要が実証済みなのに取れていない (売上に一番近い) ---
    hot = [r for r in traffic_rows
           if r[2] >= TH_VIEWS_NO_SALE and r[3] == 0 and r[0] not in sheet.get("sold_ids", set())]
    if hot:
        def label(item_id, views):
            t, c = meta.get(item_id, ("", ""))
            return f"「{(t or item_id)[:34]}」({c or '?'}) {views}回"
        n = min(DAILY_PRICE_REVIEW, len(hot))
        cats = collections.Counter(meta.get(i, ("", "?"))[1] for i, _, _, _ in hot)
        top_cat = cats.most_common(1)[0][0] if cats else "?"
        items.append(make_item(
            "P1", f"よく見られて売れていない {len(hot)}件のうち **今日 {n}件** を値下げ判定 or 同型追加",
            f"30日で {' / '.join(label(i, v) for i, _, v, _ in hot[:3])} — 閲覧はあるのに成約0。"
            f"集中は {top_cat}",
            f"上位 {n} 件を処理", "eBay Analytics × 管理スプシ",
            count=len(hot), minutes=n * MIN_PER_PRICE, button=BTN_PRICE,
            how="値下げ余地を出して該当を確認 → 余地があれば値下げ / 無ければ同系統をもう1件出す",
            effect=f"閲覧が付いている = 需要は実証済。1件成約で平均 "
                   f"¥{(econ or {}).get('avg', 0):,.0f}"))

    # --- P1: 露出が死んでいる在庫 (増やすより入れ替える) ---
    cutoff = stale_view_cutoff(traffic_rows)
    if cutoff is not None and live:
        seen = {r[0] for r in traffic_rows}
        stale = [i for i in meta if i not in seen]
        if stale and len(stale) > live * 0.3:
            cats = collections.Counter(meta[i][1] for i in stale)
            items.append(make_item(
                "P1", f"露出が死んでいる {len(stale)}件を入れ替える (今日は上位カテゴリから)",
                f"live {live}件のうち {len(stale)}件が 30日で閲覧 {cutoff}回以下 "
                f"(内訳 {', '.join(f'{k}{n}' for k, n in cats.most_common(3))})",
                "出品を増やすのではなく、動かない枠を売れ筋に入れ替える",
                "eBay Analytics (上位200件のみ返るため『以下』とだけ言える) × 管理スプシ",
                count=len(stale), minutes=20, button=BTN_END,
                how="対象を END → 空いた枠に売れている系統を出す",
                effect="出品数は足りている。回転しない在庫を抱えても露出は増えない"))

    # --- P1: 補URL ゼロ (売れた瞬間に履行不能 = キャンセル = BAN 方向) ---
    h = sheet.get("hoju") or {}
    if h.get("b0", 0) >= TH_HOJU_ZERO:
        n = min(DAILY_HOJU_CHECK, h["b0"])
        items.append(make_item(
            "P1", f"仕入元URLが0本の {h['b0']}件のうち **今日 {n}件** 目視確認",
            f"live PSA {h.get('live_psa','?')}件中 {h['b0']}件が補URL 0本 "
            f"(1-4本={h.get('b1_4','?')} / 満杯={h.get('full','?')})",
            f"{n} 件だけ確証する", "管理スプシ (backfill_status)",
            count=h["b0"], minutes=n * MIN_PER_HOJU, button=BTN_HOJU,
            how="補URL補強を回して確証する",
            effect=f"売れてから探すと履行不能→キャンセル→Defect。毎日{n}件で "
                   f"{-(-h['b0'] // n)}日で解消"))

    # --- P2: 詰まり ---
    for target, n, latest in blockers["requests"]:
        items.append(make_item(
            "P2", f"{target} の依頼 {n}件を返球する",
            f"最新: {latest}", "返球 or 督促", "requests dir", count=n, minutes=10,
            url=os.path.join(REQUESTS_ROOT, target, "requests"),
            how="requests フォルダを開いて _response.md を書く",
            effect="放置すると相手 worktree が止まる"))
    if blockers.get("pdca_pending"):
        items.append(make_item(
            "P2", f"PDCA キュー {blockers['pdca_pending']}件 — 発行済みで動いていないものを見る",
            f"最古 {blockers.get('pdca_oldest_days','?')} 日前", "滞留の原因を潰す",
            "pdca.db", count=blockers["pdca_pending"], minutes=15, url=REVIEW_DIR,
            how="review_logs の digest で再発回数を確認",
            effect="滞留が長い = 依頼しても解決しない構造問題の疑い"))
    for name, rc in blockers["tasks"]:
        items.append(make_item(
            "P2", f"定期タスクの異常を確認: {name}",
            f"LastTaskResult={rc}", "実行ログ確認", "schtasks", minutes=10, url="taskschd.msc",
            how="タスクスケジューラの履歴 → 該当時刻のログ",
            effect="無人巡回が止まると在庫/監査が黙って止まる"))
    return items


def bottleneck_note(sheet, blockers):
    """★私(AI/自動化)側の詰まりを定量化して、機能提案の材料にする。

    「件数 × 1件あたりの手作業時間」で、人手で消化しきれない山を特定する。
    """
    h = sheet.get("hoju") or {}
    cands = []
    if h.get("b0"):
        cands.append(("補URL 0本の目視確認", h["b0"], 0.5))       # 1件 30秒
    if h.get("b1_4"):
        cands.append(("補URL 補強 (1-4本)", h["b1_4"], 0.5))
    if blockers.get("pdca_pending"):
        cands.append(("PDCA キュー消化", blockers["pdca_pending"], 3.0))
    if not cands:
        return None
    name, n, per = max(cands, key=lambda c: c[1] * c[2])
    return {"name": name, "count": n, "minutes": n * per}


# =========================================================================
# 出力
# =========================================================================

def render(today, items, pace, sheet, traffic_total, bottleneck, errors, limit, econ=None):
    top = rank(items, limit)
    total_min = sum(it.get("minutes") or 0 for it in top)
    L = [f"# 今日やること {today:%Y-%m-%d} (秘書くん) — 所要 約{total_min:.0f}分", ""]

    # --- 診断: 目標に対して足りているのは何で、足りていないのは何か ---
    if econ:
        ok, ng = econ["months_ok"], econ["months_ng"]
        months = " / ".join(f"{m[5:]}月 ¥{v:,.0f}({econ['cnt_month'][m]}件)"
                            for m, v in sorted(econ["by_month"].items()))
        L += [f"**月商実績**: {months}",
              f"**平均成約 ¥{econ['avg']:,.0f}** → 月 ¥{(pace or {}).get('target', 0):,} には "
              f"**{econ['need_sales']:.1f}件/月** の成約が必要 "
              f"(目標達成 {len(ok)}ヶ月 / 未達 {len(ng)}ヶ月)", ""]
    tv = f"{traffic_total:,}回" if traffic_total else "取得不可"
    L += [f"- live 出品 **{sheet['live']}件** / 30日の総閲覧 {tv}",
          "- カテゴリ: " + ", ".join(f"{k}{v}" for k, v in sheet["by_category"].most_common(5)),
          ""]

    L.append(f"## 指示 ({len(top)}/{len(items)} 件)")
    if not top:
        L.append("- (期限もの・提案とも閾値未満。出品を回してください)")
    for i, it in enumerate(top, 1):
        m = f" — 約{it['minutes']:.0f}分" if it.get("minutes") else ""
        L += [f"### {i}. [{it['pri']}] {it['title']}{m}"]
        if it.get("button"):
            L.append(f"- **押すボタン**: 出品くん → 「{it['button']}」")
        elif it.get("url"):
            L.append(f"- **開く**: {it['url']}")
        if it.get("how"):
            L.append(f"- **やり方**: {it['how']}")
        L.append(f"- 数字: {it['why']}")
        if it.get("effect"):
            L.append(f"- 効果: {it['effect']}")
        L.append("")
    if bottleneck:
        L += ["## ★詰まり (消化でなく入口を直すべき所)",
              f"- **{bottleneck['name']}: {bottleneck['count']}件 = 手作業なら約 {bottleneck['minutes']:.0f}分**",
              "  毎日残るなら、消化速度ではなく **生成/自動確証** を直す方が効く", ""]
    if errors:
        L += ["## ⚠️ 取得できなかった source (0件ではなく不明)"] + [f"- {e}" for e in errors] + [""]
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--target", type=int, default=TARGET_JPY_DEFAULT)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--no-save", action="store_true")
    a = ap.parse_args()

    today = datetime.date.today()
    errors = []
    orders, sold_jpy, sold_rows = collect_orders(today, errors)
    traffic_total, traffic_rows = collect_traffic(errors)
    sheet = collect_sheet(errors)
    blockers = collect_blockers(errors)
    pace = month_pace(sold_jpy, today, a.target) if sold_jpy is not None else None
    econ = sales_econ(sold_rows, a.target)
    items = build_items(today, orders, sold_jpy, traffic_rows, sheet, blockers, pace, econ)
    bn = bottleneck_note(sheet, blockers)

    if a.json:
        print(json.dumps({"date": str(today), "pace": pace, "econ": econ,
                          "items": rank(items, a.limit),
                          "bottleneck": bn, "errors": errors}, ensure_ascii=False, indent=2))
        return
    text = render(today, items, pace, sheet, traffic_total, bn, errors, a.limit, econ)
    print(text)
    if not a.no_save:
        os.makedirs(REVIEW_DIR, exist_ok=True)
        p = os.path.join(REVIEW_DIR, f"today_brief_{today}.md")
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"\n→ {p}")


if __name__ == "__main__":
    main()
