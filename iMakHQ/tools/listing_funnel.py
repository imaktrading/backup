#!/usr/bin/env python3
"""
出品物フルファネル分析 (iMakHQ / 出品くんドメイン)

eBay Sell API の実データを listing 単位で結合し、改善対象を炙り出す:
  - Analytics getTrafficReport (30d): impressions / views / transactions / CTR / conversion + title
  - Fulfillment getOrders (90d): 実売数 / 実売額 (legacyItemId で結合)

3つの切り口で分類 (同一データセットから導出):
  1. 死蔵 (DEAD)            : impression も view もほぼ無い + 90d 無販売 → 露出されていない
  2. 見られて売れない (STALE) : view は付くが 90d 無販売 → 価格/競合/説明の問題
  3. タイトル弱い (WEAK_TITLE): impression は多いが CTR 下位 → タイトル/サムネが弱い

read-only。token は ebay_oauth_token_sell.json (Trading 用 ebay_oauth_token.json は触らない)。

使い方:
  python listing_funnel.py              # 30d/90d で分析、コンソール表示 + CSV 出力
  python listing_funnel.py --days 60 --sales-days 120
  python listing_funnel.py --no-csv     # CSV 出力なし (画面のみ)
"""
import argparse
import base64
import csv
import datetime
import json
import os
import statistics
import sys

import requests

# Windows コンソールの cp932 文字化け回避
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

EBAY_DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "iMakeBayAPI"))
SELL_TOKEN_FILE = os.path.join(EBAY_DIR, "ebay_oauth_token_sell.json")
KEYS_FILE = os.path.join(EBAY_DIR, "ebay keys.txt")
OUT_DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "funnel_output"))

OAUTH_TOKEN = "https://api.ebay.com/identity/v1/oauth2/token"
TRAFFIC_URL = "https://api.ebay.com/sell/analytics/v1/traffic_report"
ORDERS_URL = "https://api.ebay.com/sell/fulfillment/v1/order"
MARKETPLACE = "EBAY_US"

SCOPES = [
    "https://api.ebay.com/oauth/api_scope",
    "https://api.ebay.com/oauth/api_scope/sell.analytics.readonly",
    "https://api.ebay.com/oauth/api_scope/sell.fulfillment.readonly",
]

# 分類しきい値 (default)
TH_DEAD_VIEWS = 5        # 30d view がこれ以下
TH_DEAD_IMPR = 100       # 30d impression がこれ以下
TH_STALE_VIEWS = 30      # 30d view がこれ以上 = 見られている
TH_WEAK_IMPR = 200       # 30d impression がこれ以上 = 露出はある


def _load_keys():
    keys = {}
    with open(KEYS_FILE, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if "=" in line:
                k, v = line.split("=", 1)
                keys[k.strip()] = v.strip()
    return keys.get("AppID"), keys.get("AppSecret")


def get_access_token():
    """access_token を refresh で必ず更新してから返す (2h 期限のため毎回更新)。"""
    if not os.path.exists(SELL_TOKEN_FILE):
        sys.exit(f"sell token がありません: {SELL_TOKEN_FILE}\noauth_sell_setup.py で取得してください。")
    tok = json.load(open(SELL_TOKEN_FILE, encoding="utf-8"))
    app_id, app_secret = _load_keys()
    auth = base64.b64encode(f"{app_id}:{app_secret}".encode()).decode()
    resp = requests.post(
        OAUTH_TOKEN,
        headers={"Content-Type": "application/x-www-form-urlencoded", "Authorization": f"Basic {auth}"},
        data={"grant_type": "refresh_token", "refresh_token": tok["refresh_token"], "scope": " ".join(SCOPES)},
        timeout=20,
    )
    if resp.status_code != 200:
        sys.exit(f"token refresh 失敗: {resp.status_code} {resp.text}")
    new = resp.json()
    tok["access_token"] = new["access_token"]
    tok["expires_in"] = new.get("expires_in")
    with open(SELL_TOKEN_FILE, "w", encoding="utf-8") as f:
        json.dump(tok, f, ensure_ascii=False, indent=2)
    return tok["access_token"]


def fetch_traffic(token, days):
    """getTrafficReport (LISTING) → {item_id: {title, impr, views, txn, ctr, conv}}。"""
    H = {"Authorization": f"Bearer {token}", "Content-Type": "application/json",
         "X-EBAY-C-MARKETPLACE-ID": MARKETPLACE}
    end = datetime.date.today() - datetime.timedelta(days=1)  # 当日は未確定 → 前日まで
    start = end - datetime.timedelta(days=days - 1)
    flt = "marketplace_ids:{%s},date_range:[%s..%s]" % (MARKETPLACE, start.strftime("%Y%m%d"), end.strftime("%Y%m%d"))
    params = {
        "dimension": "LISTING",
        "metric": "LISTING_IMPRESSION_TOTAL,LISTING_VIEWS_TOTAL,TRANSACTION,CLICK_THROUGH_RATE,SALES_CONVERSION_RATE",
        "filter": flt,
        "sort": "-LISTING_IMPRESSION_TOTAL",
        "limit": "1000",
    }
    r = requests.get(TRAFFIC_URL, headers=H, params=params, timeout=90)
    if r.status_code != 200:
        sys.exit(f"getTrafficReport 失敗: {r.status_code} {r.text}")
    j = r.json()

    # metric の並び順は header.metrics で確定 (要求順とは限らない)
    metric_order = [m["key"] for m in j["header"]["metrics"]]

    # title は dimensionMetadata から item_id 別に取得
    titles = {}
    for blk in (j.get("dimensionMetadata") or []):
        for rec in blk.get("metadataRecords", []):
            iid = str(rec["value"]["value"])
            mv = rec.get("metadataValues") or []
            if mv:
                titles[iid] = mv[0].get("value", "")

    out = {}
    for rec in j.get("records", []):
        iid = str(rec["dimensionValues"][0]["value"])
        vals = {metric_order[i]: (rec["metricValues"][i].get("value") or 0) for i in range(len(metric_order))}
        out[iid] = {
            "title": titles.get(iid, ""),
            "impr": vals.get("LISTING_IMPRESSION_TOTAL", 0),
            "views": vals.get("LISTING_VIEWS_TOTAL", 0),
            "txn": vals.get("TRANSACTION", 0),
            "ctr": vals.get("CLICK_THROUGH_RATE", 0),
            "conv": vals.get("SALES_CONVERSION_RATE", 0),
        }
    capped = len(j.get("records", [])) >= 1000
    return out, capped


def fetch_sales(token, days):
    """getOrders (90d) → {item_id: {sold_qty, revenue}} (legacyItemId で集計)。"""
    H = {"Authorization": f"Bearer {token}", "Content-Type": "application/json",
         "X-EBAY-C-MARKETPLACE-ID": MARKETPLACE}
    start = (datetime.datetime.utcnow() - datetime.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    sales = {}
    offset = 0
    while True:
        r = requests.get(ORDERS_URL, headers=H,
                         params={"filter": f"creationdate:[{start}..]", "limit": "200", "offset": str(offset)},
                         timeout=90)
        if r.status_code != 200:
            sys.exit(f"getOrders 失敗: {r.status_code} {r.text}")
        j = r.json()
        for o in j.get("orders", []):
            for li in o.get("lineItems", []):
                iid = str(li.get("legacyItemId") or "")
                if not iid:
                    continue
                qty = int(li.get("quantity") or 0)
                cost = (li.get("lineItemCost") or {}).get("value") or 0
                s = sales.setdefault(iid, {"sold_qty": 0, "revenue": 0.0})
                s["sold_qty"] += qty
                s["revenue"] += float(cost)
        total = j.get("total", 0)
        offset += 200
        if offset >= total:
            break
    return sales


def classify(rows):
    """3 切り口に分類。WEAK_TITLE は view_rate(=views/impr) 下位 25% を基準にする。
    (API の CTR は小数2桁丸めで大半が 0.00 に潰れるため、自前計算の view_rate を使う)。"""
    vrs = sorted([r["vr"] for r in rows if r["impr"] >= TH_WEAK_IMPR])
    vr_q1 = statistics.quantiles(vrs, n=4)[0] if len(vrs) >= 4 else (vrs[0] if vrs else 0)

    dead, stale, weak = [], [], []
    for r in rows:
        sold = r["sold_qty"]
        if sold == 0 and r["views"] <= TH_DEAD_VIEWS and r["impr"] <= TH_DEAD_IMPR:
            dead.append(r)
        if sold == 0 and r["views"] >= TH_STALE_VIEWS:
            stale.append(r)
        if r["impr"] >= TH_WEAK_IMPR and r["vr"] <= vr_q1:
            weak.append(r)
    dead.sort(key=lambda x: (x["views"], x["impr"]))
    stale.sort(key=lambda x: -x["views"])
    weak.sort(key=lambda x: x["vr"])
    return {"DEAD": dead, "STALE": stale, "WEAK_TITLE": weak, "vr_q1": vr_q1}


def _print_section(title, note, items, limit=20):
    print(f"\n=== {title} ({len(items)}件) ===")
    print(f"   {note}")
    if not items:
        print("   (該当なし)")
        return
    print(f"   {'item_id':<14} {'impr':>6} {'views':>6} {'view%':>6} {'sold':>4}  title")
    for r in items[:limit]:
        print(f"   {r['item_id']:<14} {r['impr']:>6} {r['views']:>6} {r['vr']*100:>5.1f}% {r['sold_qty']:>4}  {r['title'][:48]}")
    if len(items) > limit:
        print(f"   ... 他 {len(items) - limit} 件 (CSV 参照)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30, help="traffic 集計日数 (default 30)")
    ap.add_argument("--sales-days", type=int, default=90, help="実売集計日数 (default 90)")
    ap.add_argument("--no-csv", action="store_true")
    args = ap.parse_args()

    token = get_access_token()
    traffic, capped = fetch_traffic(token, args.days)
    sales = fetch_sales(token, args.sales_days)

    rows = []
    for iid, t in traffic.items():
        s = sales.get(iid, {"sold_qty": 0, "revenue": 0.0})
        vr = round(t["views"] / t["impr"], 4) if t["impr"] else 0.0
        rows.append({"item_id": iid, **t, "vr": vr, "sold_qty": s["sold_qty"], "revenue": round(s["revenue"], 2)})

    print(f"\n出品物フルファネル分析  traffic={args.days}d / sales={args.sales_days}d  listing={len(rows)}件")
    if capped:
        print("⚠️ traffic が上限1000件で打切られた可能性 (全件を見るには分割取得が必要)")
    total_sold = sum(r["sold_qty"] for r in rows)
    print(f"   実売(期間内 listing にひも付く分): {total_sold}件")

    c = classify(rows)
    _print_section("① 死蔵 DEAD", f"impr<={TH_DEAD_IMPR} & views<={TH_DEAD_VIEWS} & {args.sales_days}d無販売 → 露出されていない", c["DEAD"])
    _print_section("② 見られて売れない STALE", f"views>={TH_STALE_VIEWS} & {args.sales_days}d無販売 → 価格/競合/説明", c["STALE"])
    _print_section("③ タイトル弱い WEAK_TITLE", f"impr>={TH_WEAK_IMPR} & view率<=下位25%({c['vr_q1']*100:.1f}%) → タイトル/サムネ", c["WEAK_TITLE"])

    if not args.no_csv:
        os.makedirs(OUT_DIR, exist_ok=True)
        stamp = datetime.date.today().strftime("%Y%m%d")
        path = os.path.join(OUT_DIR, f"funnel_{stamp}.csv")
        for r in rows:
            tags = []
            if r in c["DEAD"]: tags.append("DEAD")
            if r in c["STALE"]: tags.append("STALE")
            if r in c["WEAK_TITLE"]: tags.append("WEAK_TITLE")
            r["flags"] = "|".join(tags)
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["item_id", "title", "impr", "views", "vr", "txn", "ctr", "conv", "sold_qty", "revenue", "flags"])
            w.writeheader()
            for r in sorted(rows, key=lambda x: -x["impr"]):
                w.writerow(r)
        print(f"\nCSV 出力: {path}")


if __name__ == "__main__":
    main()
