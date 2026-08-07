#!/usr/bin/env python3
"""
eBay API レート上限/残量/リセットの可視化 (getRateLimits)

目的:
  funnel 等で Analytics getTrafficReport(100/日) を使う前に、残量とリセット時刻を確認する。
  これ自体は Analytics クォータを消費しない (Developer Analytics API は別枠)。

仕様 (2026-06-04 実機確認):
  - getRateLimits は **アプリトークン (client_credentials)** が必要 (user token は 204 空返し)
  - sell.analytics.traffic_report: limit=100/日, window=24h, reset は UTC
  - 日次リセットは 太平洋時間 0:00 (= 07:00 UTC = 16:00 JST, PDT 期間)

使い方:
  python ebay_rate_limits.py            # 主要リソースを表示
  python ebay_rate_limits.py --all      # 全リソース
  python ebay_rate_limits.py --filter traffic   # 名前部分一致で絞り込み
"""
import argparse
import base64
import datetime
import json
import os
import sys
import time

import requests

try:
    sys.stdout.reconfigure(encoding="utf-8")  # Windows cp932 文字化け回避
except Exception:
    pass

EBAY_DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "iMakeBayAPI"))
KEYS_FILE = os.path.join(EBAY_DIR, "ebay keys.txt")
OAUTH_TOKEN = "https://api.ebay.com/identity/v1/oauth2/token"
RATE_LIMIT_URL = "https://api.ebay.com/developer/analytics/v1_beta/rate_limit/"

# 出品/分析で実際に使う主要リソース (--all なしの既定表示。resource 実名は 2026-06-04 確認)
KEY_RESOURCES = {
    "sell.analytics.traffic_report",   # funnel の views/CTR (100/日・ボトルネック)
    "GetMyeBaySelling",                # 母集団/qty/watch (Trading・5000/日)
    "GetOrders",                       # 実売 (5000/日)
    "buy.browse",                      # 競合アクティブ数 (5000/日)
}


def _load_keys():
    keys = {}
    with open(KEYS_FILE, encoding="utf-8", errors="replace") as f:
        for line in f:
            if "=" in line:
                k, v = line.split("=", 1)
                keys[k.strip()] = v.strip()
    if not keys.get("AppID") or not keys.get("AppSecret"):
        sys.exit("AppID / AppSecret が 'ebay keys.txt' に見つかりません。")
    return keys["AppID"], keys["AppSecret"]


def _req(method, url, **kw):
    kw.setdefault("timeout", 30)
    last = None
    for _ in range(5):
        try:
            return method(url, **kw)
        except requests.exceptions.ConnectionError as e:
            last = e
            time.sleep(2)
    raise last


def get_app_token():
    """client_credentials でアプリトークンを取得 (getRateLimits は user token だと 204)。"""
    app_id, secret = _load_keys()
    auth = base64.b64encode(f"{app_id}:{secret}".encode()).decode()
    r = _req(requests.post, OAUTH_TOKEN,
             headers={"Content-Type": "application/x-www-form-urlencoded", "Authorization": f"Basic {auth}"},
             data={"grant_type": "client_credentials", "scope": "https://api.ebay.com/oauth/api_scope"})
    if r.status_code != 200:
        sys.exit(f"app token 取得失敗: {r.status_code} {r.text}")
    return r.json()["access_token"]


def fetch_rate_limits(token):
    """全リソースの rate limit を取得 → [{context, name, resource, limit, remaining, reset, window}]。"""
    r = _req(requests.get, RATE_LIMIT_URL,
             headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    if r.status_code != 200:
        sys.exit(f"getRateLimits 失敗: {r.status_code} (204=空。アプリトークンか確認)")
    out = []
    for grp in r.json().get("rateLimits", []):
        for res in grp.get("resources", []):
            for rk in res.get("rates", []):
                out.append({
                    "context": grp.get("apiContext"), "name": grp.get("apiName"),
                    "resource": res.get("name"),
                    "limit": rk.get("limit"), "remaining": rk.get("remaining"),
                    "reset": rk.get("reset"), "window": rk.get("timeWindow"),
                })
    return out


def reset_to_jst(reset_utc):
    """UTC ISO 文字列 → 'MM-DD HH:MM JST (あとNh)' 表示。"""
    if not reset_utc:
        return "?"
    try:
        d = datetime.datetime.strptime(reset_utc[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=datetime.timezone.utc)
    except ValueError:
        return reset_utc
    jst = d.astimezone(datetime.timezone(datetime.timedelta(hours=9)))
    now = datetime.datetime.now(datetime.timezone.utc)
    hrs = (d - now).total_seconds() / 3600
    return f"{jst:%m-%d %H:%M} JST (あと{hrs:.1f}h)" if hrs > 0 else f"{jst:%m-%d %H:%M} JST (経過)"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="全リソース表示")
    ap.add_argument("--filter", help="resource 名 部分一致で絞り込み")
    args = ap.parse_args()

    rows = fetch_rate_limits(get_app_token())
    if args.filter:
        rows = [r for r in rows if args.filter.lower() in (r["resource"] or "").lower()]
    elif not args.all:
        rows = [r for r in rows if r["resource"] in KEY_RESOURCES]

    rows.sort(key=lambda r: (r["remaining"] if r["remaining"] is not None else 1e9))
    print(f"{'resource':<42}{'limit':>7}{'残':>7}{'window':>8}  reset")
    print("-" * 90)
    for r in rows:
        win = f"{(r['window'] or 0)//3600}h" if r["window"] else "?"
        print(f"{(r['resource'] or '')[:42]:<42}{str(r['limit']):>7}{str(r['remaining']):>7}{win:>8}  {reset_to_jst(r['reset'])}")
    if not rows:
        print("(該当リソースなし)")


if __name__ == "__main__":
    main()
