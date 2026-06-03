#!/usr/bin/env python3
"""
出品物フルファネル分析 (iMakHQ / 出品くんドメイン)

eBay の実データを listing 単位で結合し、改善対象を炙り出す。read-only。

  - Trading GetMyeBaySelling : 全 active listing (itemId/title/価格/WatchCount/出品日) = 母集団
  - Analytics getTrafficReport: impressions/views/transactions/CTR/conversion (30d)
  - Fulfillment getOrders     : 実売数/実売額 (90d, legacyItemId で結合)

⚠️ 重要な API 制約 (2026-06-04 実機確認):
  getTrafficReport は dimension=LISTING で **impression>0 の listing しか返さない** + limit 上限200/offset無効。
  よって「全 active listing」を母集団に置き、traffic に出ない listing = impression ゼロ = 死蔵 と判定する。
  itemId を 200件ずつ listing_ids フィルタに渡して traffic を網羅取得する。

4つの切り口 (同一データセットから導出):
  1. 死蔵 (DEAD)         : 30d impression ほぼゼロ + 90d無販売 → 検索露出されていない (出品日が古いほど深刻)
  2. 見られて売れない(STALE): view付くが 90d無販売 → 価格/競合/説明の問題
  3. タイトル弱い(WEAK_TITLE): impr多いが view率(=views/impr)下位25% → タイトル/サムネが弱い
  4. ウォッチ無販売(WATCHED): WatchCount付くのに 90d無販売 → あと一押し (価格/送料/在庫不安)

token は ebay_oauth_token_sell.json (Trading 用 ebay_oauth_token.json は触らない)。

使い方:
  python listing_funnel.py                 # 30d/90d で分析、コンソール + CSV
  python listing_funnel.py --days 60 --sales-days 120
  python listing_funnel.py --no-csv
"""
import argparse
import base64
import csv
import datetime
import json
import os
import re
import statistics
import sys
import time

import requests

try:
    sys.stdout.reconfigure(encoding="utf-8")  # Windows cp932 文字化け回避
except Exception:
    pass

EBAY_DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "iMakeBayAPI"))
SELL_TOKEN_FILE = os.path.join(EBAY_DIR, "ebay_oauth_token_sell.json")
KEYS_FILE = os.path.join(EBAY_DIR, "ebay keys.txt")
OUT_DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "funnel_output"))

OAUTH_TOKEN = "https://api.ebay.com/identity/v1/oauth2/token"
TRAFFIC_URL = "https://api.ebay.com/sell/analytics/v1/traffic_report"
ORDERS_URL = "https://api.ebay.com/sell/fulfillment/v1/order"
TRADING_URL = "https://api.ebay.com/ws/api.dll"
MARKETPLACE = "EBAY_US"
TRAFFIC_CHUNK = 200  # listing_ids は1回200件まで

SCOPES = [
    "https://api.ebay.com/oauth/api_scope",
    "https://api.ebay.com/oauth/api_scope/sell.analytics.readonly",
    "https://api.ebay.com/oauth/api_scope/sell.fulfillment.readonly",
]

# 分類しきい値 (default)
TH_DEAD_IMPR = 10       # 30d impression がこれ以下 = ほぼ露出ゼロ
TH_STALE_VIEWS = 30     # 30d view がこれ以上 = 見られている
TH_WEAK_IMPR = 200      # 30d impression がこれ以上 = 露出はある
TH_WATCH = 3            # WatchCount がこれ以上 = 一定の購買シグナル


def _req(method, url, **kw):
    """DNS/接続の一過性失敗をリトライ (実環境で断続的に getaddrinfo failed が出るため)。"""
    kw.setdefault("timeout", 120)
    last = None
    for _ in range(5):
        try:
            return method(url, **kw)
        except requests.exceptions.ConnectionError as e:
            last = e
            time.sleep(2)
    raise last


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
    resp = _req(requests.post, OAUTH_TOKEN, timeout=20,
                headers={"Content-Type": "application/x-www-form-urlencoded", "Authorization": f"Basic {auth}"},
                data={"grant_type": "refresh_token", "refresh_token": tok["refresh_token"], "scope": " ".join(SCOPES)})
    if resp.status_code != 200:
        sys.exit(f"token refresh 失敗: {resp.status_code} {resp.text}")
    new = resp.json()
    tok["access_token"] = new["access_token"]
    tok["expires_in"] = new.get("expires_in")
    with open(SELL_TOKEN_FILE, "w", encoding="utf-8") as f:
        json.dump(tok, f, ensure_ascii=False, indent=2)
    return tok["access_token"]


def fetch_active(token):
    """GetMyeBaySelling ActiveList (全ページ) → {item_id: {title, price, watch, start, url}}。母集団。"""
    H = {"X-EBAY-API-CALL-NAME": "GetMyeBaySelling", "X-EBAY-API-SITEID": "0",
         "X-EBAY-API-COMPATIBILITY-LEVEL": "1193", "X-EBAY-API-IAF-TOKEN": token,
         "Content-Type": "text/xml"}
    out = {}
    page = 1
    while True:
        body = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<GetMyeBaySellingRequest xmlns="urn:ebay:apis:eBLBaseComponents">'
            '<ActiveList><Include>true</Include>'
            f'<Pagination><EntriesPerPage>200</EntriesPerPage><PageNumber>{page}</PageNumber></Pagination>'
            '</ActiveList><DetailLevel>ReturnAll</DetailLevel></GetMyeBaySellingRequest>'
        )
        r = _req(requests.post, TRADING_URL, headers=H, data=body.encode("utf-8"))
        txt = r.text
        ack = re.search(r"<Ack>(.*?)</Ack>", txt)
        if not ack or ack.group(1) not in ("Success", "Warning"):
            err = re.search(r"<LongMessage>(.*?)</LongMessage>", txt)
            sys.exit(f"GetMyeBaySelling 失敗: {err.group(1) if err else txt[:300]}")
        items = re.findall(r"<Item>(.*?)</Item>", txt, re.S)
        for blk in items:
            iid = re.search(r"<ItemID>(\d+)</ItemID>", blk)
            if not iid:
                continue
            iid = iid.group(1)
            title = re.search(r"<Title>(.*?)</Title>", blk, re.S)
            watch = re.search(r"<WatchCount>(\d+)</WatchCount>", blk)
            price = re.search(r'<CurrentPrice currencyID="[^"]*">([\d.]+)</CurrentPrice>', blk)
            start = re.search(r"<StartTime>(.*?)</StartTime>", blk)
            url = re.search(r"<ViewItemURL>(.*?)</ViewItemURL>", blk)
            out[iid] = {
                "title": (title.group(1) if title else "").replace("&amp;", "&"),
                "watch": int(watch.group(1)) if watch else 0,
                "price": float(price.group(1)) if price else 0.0,
                "start": start.group(1)[:10] if start else "",
                "url": url.group(1) if url else "",
            }
        total = re.search(r"<TotalNumberOfEntries>(\d+)</TotalNumberOfEntries>", txt)
        total = int(total.group(1)) if total else len(out)
        if len(out) >= total or not items:
            break
        page += 1
    return out


def fetch_traffic(token, item_ids, days):
    """getTrafficReport を listing_ids で200件ずつ照会 → {item_id: {impr,views,txn,ctr,conv}}。
    traffic に出ない id = impression ゼロ (= 戻り値に含まれない)。"""
    H = {"Authorization": f"Bearer {token}", "Content-Type": "application/json",
         "X-EBAY-C-MARKETPLACE-ID": MARKETPLACE}
    end = datetime.date.today() - datetime.timedelta(days=1)  # 当日=未来エラー
    start = end - datetime.timedelta(days=days - 1)
    date_part = "marketplace_ids:{%s},date_range:[%s..%s]" % (MARKETPLACE, start.strftime("%Y%m%d"), end.strftime("%Y%m%d"))
    out = {}
    for i in range(0, len(item_ids), TRAFFIC_CHUNK):
        chunk = item_ids[i:i + TRAFFIC_CHUNK]
        flt = date_part + ",listing_ids:{%s}" % "|".join(chunk)
        r = _req(requests.get, TRAFFIC_URL, headers=H, params={
            "dimension": "LISTING",
            "metric": "LISTING_IMPRESSION_TOTAL,LISTING_VIEWS_TOTAL,TRANSACTION,CLICK_THROUGH_RATE,SALES_CONVERSION_RATE",
            "filter": flt})
        if r.status_code != 200:
            sys.exit(f"getTrafficReport 失敗: {r.status_code} {r.text}")
        j = r.json()
        order = [m["key"] for m in j["header"]["metrics"]]
        for rec in j.get("records", []):
            iid = str(rec["dimensionValues"][0]["value"])
            vals = {order[k]: (rec["metricValues"][k].get("value") or 0) for k in range(len(order))}
            out[iid] = {
                "impr": vals.get("LISTING_IMPRESSION_TOTAL", 0),
                "views": vals.get("LISTING_VIEWS_TOTAL", 0),
                "txn": vals.get("TRANSACTION", 0),
                "ctr": vals.get("CLICK_THROUGH_RATE", 0),
                "conv": vals.get("SALES_CONVERSION_RATE", 0),
            }
    return out


def fetch_sales(token, days):
    """getOrders (90d) → {item_id: {sold_qty, revenue}} (legacyItemId で集計)。"""
    H = {"Authorization": f"Bearer {token}", "Content-Type": "application/json",
         "X-EBAY-C-MARKETPLACE-ID": MARKETPLACE}
    start = (datetime.datetime.utcnow() - datetime.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    sales = {}
    offset = 0
    while True:
        r = _req(requests.get, ORDERS_URL, headers=H,
                 params={"filter": f"creationdate:[{start}..]", "limit": "200", "offset": str(offset)})
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


def _age_days(start_str):
    if not start_str:
        return 0
    try:
        d = datetime.date.fromisoformat(start_str)
        return (datetime.date.today() - d).days
    except ValueError:
        return 0


def classify(rows):
    """4 切り口に分類。WEAK_TITLE は view_rate(=views/impr) 下位25%で弁別
    (API CTR は小数2桁丸めで 0.00 に潰れるため自前計算を使う)。"""
    vrs = sorted([r["vr"] for r in rows if r["impr"] >= TH_WEAK_IMPR])
    vr_q1 = statistics.quantiles(vrs, n=4)[0] if len(vrs) >= 4 else (vrs[0] if vrs else 0)

    dead, stale, weak, watched = [], [], [], []
    for r in rows:
        sold = r["sold_qty"]
        if sold == 0 and r["impr"] <= TH_DEAD_IMPR:
            dead.append(r)
        if sold == 0 and r["views"] >= TH_STALE_VIEWS:
            stale.append(r)
        if r["impr"] >= TH_WEAK_IMPR and r["vr"] <= vr_q1:
            weak.append(r)
        if sold == 0 and r["watch"] >= TH_WATCH:
            watched.append(r)
    dead.sort(key=lambda x: -x["age_days"])      # 古い死蔵ほど深刻
    stale.sort(key=lambda x: -x["views"])
    weak.sort(key=lambda x: x["vr"])
    watched.sort(key=lambda x: -x["watch"])
    return {"DEAD": dead, "STALE": stale, "WEAK_TITLE": weak, "WATCHED": watched, "vr_q1": vr_q1}


def _print_section(title, note, items, cols, limit=20):
    print(f"\n=== {title} ({len(items)}件) ===")
    print(f"   {note}")
    if not items:
        print("   (該当なし)")
        return
    print("   " + cols(None, header=True))
    for r in items[:limit]:
        print("   " + cols(r))
    if len(items) > limit:
        print(f"   ... 他 {len(items) - limit} 件 (CSV 参照)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30, help="traffic 集計日数 (default 30)")
    ap.add_argument("--sales-days", type=int, default=90, help="実売集計日数 (default 90)")
    ap.add_argument("--no-csv", action="store_true")
    args = ap.parse_args()

    token = get_access_token()
    print("active listing 取得中 (GetMyeBaySelling)...", flush=True)
    active = fetch_active(token)
    print(f"  active = {len(active)}件", flush=True)
    print(f"traffic 取得中 (listing_ids 200件ずつ, {-(-len(active) // TRAFFIC_CHUNK)}回)...", flush=True)
    traffic = fetch_traffic(token, list(active.keys()), args.days)
    print(f"  traffic 出現 (impr>0含む) = {len(traffic)}件", flush=True)
    sales = fetch_sales(token, args.sales_days)

    rows = []
    for iid, a in active.items():
        t = traffic.get(iid, {"impr": 0, "views": 0, "txn": 0, "ctr": 0, "conv": 0})
        s = sales.get(iid, {"sold_qty": 0, "revenue": 0.0})
        vr = round(t["views"] / t["impr"], 4) if t["impr"] else 0.0
        rows.append({
            "item_id": iid, "title": a["title"], "price": a["price"], "watch": a["watch"],
            "start": a["start"], "age_days": _age_days(a["start"]), "url": a["url"],
            "impr": t["impr"], "views": t["views"], "txn": t["txn"], "ctr": t["ctr"], "conv": t["conv"],
            "vr": vr, "sold_qty": s["sold_qty"], "revenue": round(s["revenue"], 2),
        })

    no_impr = sum(1 for r in rows if r["impr"] == 0)
    total_sold = sum(r["sold_qty"] for r in rows)
    print(f"\n出品物フルファネル分析  traffic={args.days}d / sales={args.sales_days}d")
    print(f"   active listing={len(rows)}件 / うち 30d impression ゼロ={no_impr}件 ({no_impr*100//max(len(rows),1)}%) / 90d実売={total_sold}件")

    c = classify(rows)

    def cols_dead(r, header=False):
        if header:
            return f"{'item_id':<14} {'impr':>5} {'age日':>5} {'watch':>5} {'$':>7}  title"
        return f"{r['item_id']:<14} {r['impr']:>5} {r['age_days']:>5} {r['watch']:>5} {r['price']:>7.0f}  {r['title'][:46]}"

    def cols_view(r, header=False):
        if header:
            return f"{'item_id':<14} {'impr':>6} {'views':>6} {'view%':>6} {'watch':>5} {'$':>6}  title"
        return f"{r['item_id']:<14} {r['impr']:>6} {r['views']:>6} {r['vr']*100:>5.1f}% {r['watch']:>5} {r['price']:>6.0f}  {r['title'][:42]}"

    _print_section("① 死蔵 DEAD", f"30d impr<={TH_DEAD_IMPR} & {args.sales_days}d無販売 → 検索露出なし (古い順)", c["DEAD"], cols_dead)
    _print_section("② 見られて売れない STALE", f"30d views>={TH_STALE_VIEWS} & {args.sales_days}d無販売 → 価格/競合", c["STALE"], cols_view)
    _print_section("③ タイトル弱い WEAK_TITLE", f"impr>={TH_WEAK_IMPR} & view率<=下位25%({c['vr_q1']*100:.1f}%) → タイトル/サムネ", c["WEAK_TITLE"], cols_view)
    _print_section("④ ウォッチ無販売 WATCHED", f"WatchCount>={TH_WATCH} & {args.sales_days}d無販売 → あと一押し(価格/送料)", c["WATCHED"], cols_view)

    if not args.no_csv:
        os.makedirs(OUT_DIR, exist_ok=True)
        stamp = datetime.date.today().strftime("%Y%m%d")
        path = os.path.join(OUT_DIR, f"funnel_{stamp}.csv")
        for r in rows:
            tags = []
            if r in c["DEAD"]: tags.append("DEAD")
            if r in c["STALE"]: tags.append("STALE")
            if r in c["WEAK_TITLE"]: tags.append("WEAK_TITLE")
            if r in c["WATCHED"]: tags.append("WATCHED")
            r["flags"] = "|".join(tags)
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["item_id", "title", "price", "watch", "start", "age_days",
                                              "impr", "views", "vr", "txn", "ctr", "conv",
                                              "sold_qty", "revenue", "flags", "url"])
            w.writeheader()
            for r in sorted(rows, key=lambda x: (-x["impr"], -x["watch"])):
                w.writerow(r)
        print(f"\nCSV 出力: {path}")


if __name__ == "__main__":
    main()
