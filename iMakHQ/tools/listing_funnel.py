#!/usr/bin/env python3
"""
出品物フルファネル分析 (iMakHQ / 出品くんドメイン)

データ源 = 出品くん「今、見る」が保存する Seller Hub snapshot
  (C:/dev/iMak_data/seller_hub/snapshot_active_all_*.csv)。
  → 全4サイト(US/EU/UK/AU)・views/watchers/quantity/price/listed_date を listing 単位で網羅済。
  Selenium scrape 由来なので eBay API クォータ不要。「今見る」と同じ母集団を保証する。

ここに分析層を乗せて「今見る」超えにする:
  + getOrders(90d) で実売を join (snapshot に無い「売れたか」を補完)
  + 在庫(qty=0)を分離 → 「今見る」の views=0 死蔵に混入していた在庫切れ品を除外
  + サイト別 / 在庫あり限定の actionable バケツ

⚠️ Analytics の impressions/CTR/転換率は別レイヤ(US-only/クォータ)。本スクリプトは触れない。

切り口 (在庫あり=qty!=0 に限定):
  1. 死蔵 DEAD     : views==0 → 一度も見られていない (在庫切れは除外済の真の死蔵)
  2. 見られて売れない STALE : views多いが 90d無販売 → 価格/競合/説明
  3. ウォッチ無販売 WATCHED : watchers付くのに 90d無販売 → あと一押し
  + 購買意欲 BUY_INTENT     : watch/view 比率上位 (「今見る」再現)

使い方:
  python listing_funnel.py                # 最新 snapshot + 実売、コンソール + CSV
  python listing_funnel.py --no-sales     # snapshot のみ (API 一切なし)
  python listing_funnel.py --site US      # 特定サイトに絞る
"""
import argparse
import base64
import csv
import datetime
import glob
import json
import os
import sys
import time

import requests

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

EBAY_DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "iMakeBayAPI"))
SELL_TOKEN_FILE = os.path.join(EBAY_DIR, "ebay_oauth_token_sell.json")
KEYS_FILE = os.path.join(EBAY_DIR, "ebay keys.txt")
SNAPSHOT_DIR = r"C:\dev\iMak_data\seller_hub"
OUT_DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "funnel_output"))

OAUTH_TOKEN = "https://api.ebay.com/identity/v1/oauth2/token"
ORDERS_URL = "https://api.ebay.com/sell/fulfillment/v1/order"
MARKETPLACE = "EBAY_US"
SCOPES = ["https://api.ebay.com/oauth/api_scope",
          "https://api.ebay.com/oauth/api_scope/sell.analytics.readonly",
          "https://api.ebay.com/oauth/api_scope/sell.fulfillment.readonly"]

TH_STALE_VIEWS = 50   # 累計 view がこれ以上 = 十分見られている
TH_WATCH = 3          # watchers がこれ以上 = 購買シグナル


def _req(method, url, **kw):
    kw.setdefault("timeout", 90)
    last = None
    for _ in range(5):
        try:
            return method(url, **kw)
        except requests.exceptions.ConnectionError as e:
            last = e
            time.sleep(2)
    raise last


def _int(v):
    try:
        return int(str(v).strip().replace(",", ""))
    except (ValueError, AttributeError):
        return 0


def _float(v):
    try:
        return float(str(v).strip().replace(",", ""))
    except (ValueError, AttributeError):
        return 0.0


def latest_snapshot():
    files = glob.glob(os.path.join(SNAPSHOT_DIR, "snapshot_active_all_*.csv"))
    if not files:
        sys.exit(f"snapshot がありません: {SNAPSHOT_DIR}\n出品くん『今、見る』を実行して snapshot を作ってください。")
    return max(files, key=os.path.getmtime)


def load_snapshot(path, site=None):
    """Seller Hub snapshot → listing rows。site 指定で絞り込み。"""
    rows = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            s = (r.get("listing_site") or "").strip()
            if site and s.upper() != site.upper():
                continue
            qa = (r.get("quantity_available") or "").strip()
            rows.append({
                "item_id": (r.get("item_id") or "").strip(),
                "title": (r.get("title") or "").strip(),
                "price": _float(r.get("price_usd")),
                "site": s,
                "views": _int(r.get("views")),
                "watch": _int(r.get("watchers")),
                "qty": _int(qa) if qa != "" else -1,
                "listed": (r.get("listed_date") or "").strip(),
            })
    return rows


def get_access_token():
    if not os.path.exists(SELL_TOKEN_FILE):
        sys.exit(f"sell token がありません: {SELL_TOKEN_FILE}")
    tok = json.load(open(SELL_TOKEN_FILE, encoding="utf-8"))
    keys = {}
    with open(KEYS_FILE, encoding="utf-8", errors="replace") as f:
        for line in f:
            if "=" in line:
                k, v = line.split("=", 1)
                keys[k.strip()] = v.strip()
    auth = base64.b64encode(f"{keys.get('AppID')}:{keys.get('AppSecret')}".encode()).decode()
    resp = _req(requests.post, OAUTH_TOKEN, timeout=20,
                headers={"Content-Type": "application/x-www-form-urlencoded", "Authorization": f"Basic {auth}"},
                data={"grant_type": "refresh_token", "refresh_token": tok["refresh_token"], "scope": " ".join(SCOPES)})
    if resp.status_code != 200:
        sys.exit(f"token refresh 失敗: {resp.status_code} {resp.text}")
    tok["access_token"] = resp.json()["access_token"]
    with open(SELL_TOKEN_FILE, "w", encoding="utf-8") as f:
        json.dump(tok, f, ensure_ascii=False, indent=2)
    return tok["access_token"]


def fetch_sales(token, days):
    """getOrders (90d) → {item_id: {sold_qty, revenue}} (legacyItemId で集計)。"""
    H = {"Authorization": f"Bearer {token}", "Content-Type": "application/json",
         "X-EBAY-C-MARKETPLACE-ID": MARKETPLACE}
    start = (datetime.datetime.utcnow() - datetime.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    sales, offset = {}, 0
    while True:
        r = _req(requests.get, ORDERS_URL, headers=H,
                 params={"filter": f"creationdate:[{start}..]", "limit": "200", "offset": str(offset)})
        if r.status_code != 200:
            raise RuntimeError(f"getOrders 失敗: {r.status_code} {r.text[:200]}")
        j = r.json()
        for o in j.get("orders", []):
            for li in o.get("lineItems", []):
                iid = str(li.get("legacyItemId") or "")
                if not iid:
                    continue
                cost = (li.get("lineItemCost") or {}).get("value") or 0
                s = sales.setdefault(iid, {"sold_qty": 0, "revenue": 0.0})
                s["sold_qty"] += _int(li.get("quantity"))
                s["revenue"] += float(cost)
        total = j.get("total", 0)
        offset += 200
        if offset >= total:
            break
    return sales


def _age_days(listed):
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d"):
        try:
            d = datetime.datetime.strptime(listed[:10], fmt).date()
            return (datetime.date.today() - d).days
        except (ValueError, TypeError):
            continue
    return 0


def classify(rows):
    """在庫(qty)を踏まえ分類。qty==0(在庫切れ)は OUT_OF_STOCK に隔離 (eBay が検索非表示=views0が正常)。
    改善対象は在庫あり(qty!=0)に限定。qty==-1(不明)は安全側で在庫あり扱い。"""
    in_stock = [r for r in rows if r["qty"] != 0]
    oos = [r for r in rows if r["qty"] == 0]

    dead, stale, watched = [], [], []
    for r in in_stock:
        sold = r.get("sold_qty", 0)
        if r["views"] == 0:
            dead.append(r)
        if sold == 0 and r["views"] >= TH_STALE_VIEWS:
            stale.append(r)
        if sold == 0 and r["watch"] >= TH_WATCH:
            watched.append(r)
    dead.sort(key=lambda x: -x["age_days"])       # 古い死蔵ほど深刻
    stale.sort(key=lambda x: -x["views"])
    watched.sort(key=lambda x: -x["watch"])
    # 購買意欲: views>=10 で watch/view 比率上位
    intent = [r for r in in_stock if r["views"] >= 10 and r["watch"] > 0]
    intent.sort(key=lambda x: x["watch"] / x["views"], reverse=True)
    return {"DEAD": dead, "STALE": stale, "WATCHED": watched, "BUY_INTENT": intent, "OUT_OF_STOCK": oos}


def _section(title, note, items, limit=20):
    print(f"\n=== {title} ({len(items)}件) ===")
    print(f"   {note}")
    if not items:
        print("   (該当なし)")
        return
    print(f"   {'item_id':<13}{'site':>4} {'views':>6} {'watch':>5} {'age日':>5} {'sold':>4} {'$':>6}  title")
    for r in items[:limit]:
        print(f"   {r['item_id']:<13}{r['site']:>4} {r['views']:>6} {r['watch']:>5} {r['age_days']:>5} "
              f"{r.get('sold_qty',0):>4} {r['price']:>6.0f}  {r['title'][:40]}")
    if len(items) > limit:
        print(f"   ... 他 {len(items) - limit} 件 (CSV 参照)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-sales", action="store_true", help="実売 join をスキップ (API 一切なし)")
    ap.add_argument("--sales-days", type=int, default=90)
    ap.add_argument("--site", help="サイト絞り込み (US/EU/UK/AU)")
    ap.add_argument("--no-csv", action="store_true")
    args = ap.parse_args()

    snap = latest_snapshot()
    rows = load_snapshot(snap, site=args.site)
    print(f"snapshot: {os.path.basename(snap)}  listing={len(rows)}件" + (f" (site={args.site})" if args.site else ""))

    sales_ok = False
    if not args.no_sales:
        try:
            sales = fetch_sales(get_access_token(), args.sales_days)
            sales_ok = True
            print(f"実売 join: getOrders {args.sales_days}d → {sum(s['sold_qty'] for s in sales.values())}件 / {len(sales)} listing")
        except Exception as e:
            sales = {}
            print(f"⚠️ 実売取得失敗 ({e}) → sold=0 扱いで継続 (「無販売」系は参考値)")
    else:
        sales = {}

    for r in rows:
        s = sales.get(r["item_id"], {"sold_qty": 0, "revenue": 0.0})
        r["sold_qty"] = s["sold_qty"]
        r["revenue"] = round(s["revenue"], 2)
        r["age_days"] = _age_days(r["listed"])

    # サマリー
    from collections import Counter
    site_c = Counter(r["site"] for r in rows)
    oos = sum(1 for r in rows if r["qty"] == 0)
    in_stock = [r for r in rows if r["qty"] != 0]
    instock_v0 = sum(1 for r in in_stock if r["views"] == 0)
    n = max(len(rows), 1)
    print(f"\n出品物フルファネル分析 (snapshot ベース)")
    print(f"   listing={len(rows)}  サイト別={dict(site_c)}")
    print(f"   在庫切れqty0={oos}件({oos*100//n}%)  在庫あり={len(in_stock)}件")
    print(f"   ※在庫切れは検索非表示=views0が正常 (改善対象外)。下記は在庫あり限定。")
    print(f"   在庫ありで views=0 = {instock_v0}件 = 在庫あるのに一度も見られていない真の死蔵")
    if sales_ok:
        print(f"   実売(90d)= {sum(r['sold_qty'] for r in rows)}件")

    c = classify(rows)
    sale_note = "" if sales_ok else " ※実売未取得につき参考値"
    _section("① 死蔵 DEAD (在庫あり)", "在庫あり & views==0 → 在庫あるのに一度も見られていない (古い順)", c["DEAD"])
    _section("② 見られて売れない STALE", f"在庫あり & 累計views>={TH_STALE_VIEWS} & 90d無販売 → 価格/競合{sale_note}", c["STALE"])
    _section("③ ウォッチ無販売 WATCHED", f"在庫あり & watchers>={TH_WATCH} & 90d無販売 → あと一押し{sale_note}", c["WATCHED"])
    _section("④ 購買意欲 BUY_INTENT", "在庫あり & views>=10 & watch/view比率上位 → 売れる寸前(「今見る」再現)", c["BUY_INTENT"], limit=10)
    print(f"\n(参考) 在庫切れ OUT_OF_STOCK = {len(c['OUT_OF_STOCK'])}件 — 仕入れ不可で取下げ済 (改善対象外)")

    if not args.no_csv:
        os.makedirs(OUT_DIR, exist_ok=True)
        path = os.path.join(OUT_DIR, f"funnel_{datetime.date.today():%Y%m%d}.csv")
        for r in rows:
            tags = []
            if r["qty"] == 0: tags.append("OUT_OF_STOCK")
            if r in c["DEAD"]: tags.append("DEAD")
            if r in c["STALE"]: tags.append("STALE")
            if r in c["WATCHED"]: tags.append("WATCHED")
            r["flags"] = "|".join(tags)
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["item_id", "title", "site", "price", "qty", "views", "watch",
                                              "listed", "age_days", "sold_qty", "revenue", "flags"])
            w.writeheader()
            for r in sorted(rows, key=lambda x: (-x["views"], -x["watch"])):
                w.writerow({k: r.get(k) for k in w.fieldnames})
        print(f"CSV 出力: {path}")


if __name__ == "__main__":
    main()
