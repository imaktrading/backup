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


def make_item(pri, title, why, action, source, count=None, days_left_=None):
    return {"pri": pri, "title": title, "why": why, "action": action,
            "source": source, "count": count, "days_left": days_left_}


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
    """未発送注文 + 今月の成約額。Returns: (unshipped[], sold_jpy, fx)"""
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

    since = (datetime.datetime.utcnow() - datetime.timedelta(days=45)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
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
        return [], None, None

    unshipped, sold_jpy = [], 0.0
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
        if cd[:7] == today.strftime("%Y-%m"):
            sold_jpy += jpy
        if o.get("orderFulfillmentStatus") != "FULFILLED" and pay == "PAID":
            inst = (li.get("lineItemFulfillmentInstructions") or {})
            unshipped.append({"date": cd, "title": (li.get("title") or "")[:60],
                              "amount": f"{cur} {val:.2f}", "jpy": jpy,
                              "ship_by": (inst.get("shipByDate") or "")[:10]})
    return unshipped, sold_jpy, fx("USD")


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
        return 0, []
    rows = []
    for r in d.get("records", []):
        dim = [v.get("value") for v in r.get("dimensionValues", [])]
        met = [v.get("value") for v in r.get("metricValues", [])]
        if not dim or len(met) < 3:
            continue
        rows.append((dim[0], int(met[0] or 0), int(met[1] or 0), int(met[2] or 0)))
    return sum(r[2] for r in rows), rows


def collect_sheet(errors):
    """管理スプシ: live 件数 / カテゴリ内訳 / 出品ペース / 補URL 滞留。"""
    out = {"live": 0, "by_category": collections.Counter(), "listed_recent": {},
           "hoju": None, "sold_ids": set(), "live_meta": {}}
    try:
        sys.path.insert(0, _HERE)
        import psa_hoju_fill as ph
        vals = ph._read_high()
    except Exception as e:
        errors.append(f"管理スプシ 取得不可: {type(e).__name__}: {str(e)[:80]}")
        return out
    hdr = {h: i for i, h in enumerate(vals[0])}
    need = ("itemID", "売り切れ", "カテゴリ", "出品日時")
    if not all(k in hdr for k in need):
        errors.append("管理スプシ: 想定列が無い (列構成が変わった可能性)")
        return out
    listed = collections.Counter()
    for r in vals[1:]:
        if len(r) <= max(hdr[k] for k in need):
            continue
        item = r[hdr["itemID"]].strip()
        if not item:
            continue
        if r[hdr["売り切れ"]].strip():
            out["sold_ids"].add(item)
            continue
        out["live"] += 1
        cat = r[hdr["カテゴリ"]].strip() or "(未分類)"
        out["by_category"][cat] += 1
        # 表示名は **`タイトル`(和文) を優先**。PSA 行は `Title` 列に cert 番号が入っており
        # そちらを使うと「138056961」のような数字が並んで人が読めない (2026-08-01 実測)。
        name = ""
        for key in ("タイトル", "Title"):
            i = hdr.get(key)
            if i is not None and i < len(r) and r[i].strip():
                name = r[i].strip()
                break
        out["live_meta"][item] = (name, cat)
        d = r[hdr["出品日時"]][:10]
        if d:
            listed[d] += 1
    out["listed_recent"] = dict(sorted(listed.items())[-14:])
    try:
        out["hoju"] = ph.backfill_status(vals)
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

def build_items(today, orders, sold_jpy, traffic_rows, sheet, blockers, pace):
    items = []

    # --- P0: 期限もの ---
    for o in orders:
        dl = days_left(o["ship_by"], today)
        items.append(make_item(
            "P0", f"発送: {o['title']}",
            f"{o['date']} 注文 / {o['amount']} 入金済 / 発送期限 {o['ship_by']}"
            + (f" (残 {dl} 日)" if dl is not None else ""),
            "仕入れ → 発送。期限超過は Late shipment = Defect に直結",
            "eBay Fulfillment API", days_left_=dl))

    # --- P1: 売上ペース ---
    # 1日分未満の遅れは出さない。月初は「経過1日 = 想定¥3,226 に未達」で必ず遅れ判定になり、
    # 毎朝ノイズが1件増えるだけになる (2026-08-01 初版で実際にそうなった)。
    if pace and pace["gap"] > 0 and pace["gap"] >= pace["need_per_day"]:
        items.append(make_item(
            "P1", f"売上ペース遅れ ¥{pace['gap']:,.0f}",
            f"今月 ¥{pace['sold']:,.0f} / 目標 ¥{pace['target']:,.0f} "
            f"(経過 {pace['elapsed']}/{pace['days_in_month']}日 = 想定 ¥{pace['expected']:,.0f})",
            f"残 {pace['remaining_days']} 日で ¥{pace['need_per_day']:,.0f}/日 が必要",
            "eBay 注文 + 為替 SSOT", count=int(pace["gap"])))

    # --- P1: 見られているのに売れていない (= 需要は実証済、供給か価格の問題) ---
    meta = sheet.get("live_meta") or {}
    hot = [r for r in traffic_rows
           if r[2] >= TH_VIEWS_NO_SALE and r[3] == 0 and r[0] not in sheet.get("sold_ids", set())]
    if hot:
        def label(item_id, views):
            t, c = meta.get(item_id, ("", ""))
            name = (t or item_id)[:44]
            return f"「{name}」({c or '?'}) {views}回" if t else f"{item_id} {views}回"
        cats = collections.Counter(meta.get(i, ("", "?"))[1] for i, _, _, _ in hot)
        items.append(make_item(
            "P1", f"よく見られているのに売れていない {len(hot)}件",
            "30日の閲覧 上位: " + " / ".join(label(i, v) for i, _, v, _ in hot[:3])
            + f" — 閲覧の集中カテゴリ: {', '.join(f'{k}{n}件' for k, n in cats.most_common(3))}",
            "需要は実証済。**同系統を追加出品**するのが一番速い。動かないものは価格抵抗を疑う",
            "eBay Analytics (LISTING次元) × 管理スプシ", count=len(hot)))

    # --- P1: カテゴリ偏り ---
    top_cat, ratio, thin = category_skew(sheet["by_category"])
    if top_cat and ratio >= TH_CATEGORY_SKEW:
        items.append(make_item(
            "P1", f"出品が {top_cat} に偏り {ratio:.0%}",
            f"live {sheet['live']}件中 {sheet['by_category'][top_cat]}件が {top_cat}。"
            + (f"手薄: {', '.join(thin[:4])}" if thin else ""),
            f"{top_cat} 以外を増やす。1カテゴリ依存は相場・規約変更で売上が丸ごと止まる",
            "管理スプシ", count=sheet["by_category"][top_cat]))

    # --- P1: 補URL ゼロ (履行不能リスク) ---
    h = sheet.get("hoju") or {}
    if h.get("b0", 0) >= TH_HOJU_ZERO:
        items.append(make_item(
            "P1", f"仕入元URLが1本も無い出品 {h['b0']}件",
            f"live PSA {h.get('live_psa','?')}件中 {h['b0']}件が補URL 0本 "
            f"(1-4本={h.get('b1_4','?')} / 満杯={h.get('full','?')})",
            "売れてから探すと履行不能 → キャンセル → Defect。補URL目視確認を回す",
            "管理スプシ (backfill_status)", count=h["b0"]))

    # --- P2: 詰まり (作業が滞留している場所) ---
    for target, n, latest in blockers["requests"]:
        items.append(make_item(
            "P2", f"{target} の未処理依頼 {n}件",
            f"最新: {latest}",
            "返球するか、相手ボールなら滞留日数を見て督促",
            "requests dir", count=n))
    if blockers.get("pdca_pending"):
        items.append(make_item(
            "P2", f"PDCA キュー pending {blockers['pdca_pending']}件",
            f"最古 {blockers.get('pdca_oldest_days','?')} 日前",
            "次の監査で Catalog に発行される。滞留が長い = 発行しても解決していない疑い",
            "pdca.db", count=blockers["pdca_pending"]))
    for name, rc in blockers["tasks"]:
        items.append(make_item(
            "P2", f"定期タスク異常終了: {name}",
            f"LastTaskResult={rc}",
            "実行ログを確認。無人巡回が止まると気づかないまま在庫/監査が止まる",
            "schtasks"))
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

def render(today, items, pace, sheet, traffic_total, bottleneck, errors, limit):
    L = [f"# 今日のブリーフ {today:%Y-%m-%d} (秘書くん)", ""]
    if pace:
        mark = "✅ 順調" if pace["on_track"] else "⚠️ 遅れ"
        L += [f"**月商 ¥{pace['target']:,} に対し 今月 ¥{pace['sold']:,.0f}** — {mark} "
              f"(経過 {pace['elapsed']}/{pace['days_in_month']}日 / 残 {pace['remaining_days']}日 "
              f"→ 必要 ¥{pace['need_per_day']:,.0f}/日)", ""]
    L += [f"- live 出品 {sheet['live']}件 / 30日の総閲覧 {traffic_total:,} 回",
          f"- 直近の出品ペース: " + ", ".join(f"{d[5:]}={n}" for d, n in list(sheet["listed_recent"].items())[-7:]),
          ""]
    top = rank(items, limit)
    L.append(f"## 今日やること ({len(top)}/{len(items)} 件)")
    if not top:
        L.append("- (期限もの・提案とも閾値未満。出品を回してください)")
    for i, it in enumerate(top, 1):
        L += [f"### {i}. [{it['pri']}] {it['title']}",
              f"- 根拠: {it['why']}",
              f"- やること: {it['action']}",
              f"- 出所: {it['source']}", ""]
    if bottleneck:
        L += ["## ★詰まりの定量化 (自動化すべき所)",
              f"- **{bottleneck['name']}: {bottleneck['count']}件 = 手作業なら約 {bottleneck['minutes']:.0f}分**",
              "  この山が毎日残るなら、消化速度ではなく **入口(生成/自動確証)** を直す方が効く", ""]
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
    orders, sold_jpy, fxusd = collect_orders(today, errors)
    traffic_total, traffic_rows = collect_traffic(errors)
    sheet = collect_sheet(errors)
    blockers = collect_blockers(errors)
    pace = month_pace(sold_jpy, today, a.target) if sold_jpy is not None else None
    items = build_items(today, orders, sold_jpy, traffic_rows, sheet, blockers, pace)
    bn = bottleneck_note(sheet, blockers)

    if a.json:
        print(json.dumps({"date": str(today), "pace": pace, "items": rank(items, a.limit),
                          "bottleneck": bn, "errors": errors}, ensure_ascii=False, indent=2))
        return
    text = render(today, items, pace, sheet, traffic_total, bn, errors, a.limit)
    print(text)
    if not a.no_save:
        os.makedirs(REVIEW_DIR, exist_ok=True)
        p = os.path.join(REVIEW_DIR, f"today_brief_{today}.md")
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"\n→ {p}")


if __name__ == "__main__":
    main()
