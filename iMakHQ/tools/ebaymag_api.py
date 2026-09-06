#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""eBaymag の中身を **ブラウザ無しで** 取る (2026-09-06).

なぜ:
    画面から拾うと毎回ブラウザが立ち上がり、そのたびにログインを聞かれていた
    (eBaymag のログイン cookie はセッション限りで、閉じると消えるため)。
    ログインは1回だけにして、以降は保存した cookie で GraphQL を直接叩く。

    画面が使っているのと同じ問い合わせなので、画面に出ることは全部取れる。

使い方:
    python ebaymag_api.py --login          # cookie が切れた時だけ (ブラウザが開く)
    python ebaymag_api.py --errors         # エラーのある商品を一覧にする
    python ebaymag_api.py --policies       # 配送ポリシー一覧

出力はデスクトップに CSV。
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys
import time

sys.path.insert(0, r"C:\dev\iMak\iMakeBayAPI")
try:
    import dns_cache  # noqa: F401
except Exception:                                                 # noqa: BLE001
    pass
import requests  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ebaymag_dump import COOKIE_FILE, DESKTOP  # noqa: E402

GQL = "https://ebaymag.com/graphql"

# eBay のサイト番号 → 国 (どこが弾かれているかを人が読める形で出す)
SITE = {0: "US", 2: "CA", 3: "UK", 15: "AU", 16: "AT", 23: "BE", 71: "FR",
        77: "DE", 100: "eBayMotors", 101: "IT", 146: "NL", 186: "ES",
        193: "CH", 196: "?", 205: "IE", 210: "CA-FR"}

PRODUCTS_QUERY = """
query Products($first: Int, $after: String, $filters: ProductFilterInput) {
  products(first: $first, after: $after, filters: $filters) {
    nodes {
      totalQuantity
      url
      shippingProfileId
      variations { sku quantity }
      title
      id
      listings {
        id
        site { id }
        selected
        published
        synchronizable
        notSynchronizableReasons
        # ★action は eBaymag 側が 500 を返すので取らない (2026-09-06 実測)
        problems { id severity text field context }
      }
    }
    pageInfo { hasNextPage endCursor }
  }
}
"""

EMPTY_FILTER = {"archived": False, "name": None, "selectedOnSiteId": None, "sku": None,
                "price": {"min": None, "max": None},
                "quantity": {"min": None, "max": None},
                "status": None, "rating": False, "shippingId": None, "gpsrCategory": None}


# ── 純関数 (test 可) ────────────────────────────────────────────────
def site_name(site_id):
    """サイト番号 → 国名。知らない番号はそのまま数字で出す (黙って落とさない)。"""
    return SITE.get(site_id, str(site_id))


def bad_sites(node):
    """その商品で **問題が付いているサイト** [(国, 件数)]。"""
    out = []
    for l_ in node.get("listings") or []:
        probs = l_.get("problems") or []
        if probs:
            out.append((site_name((l_.get("site") or {}).get("id")), len(probs)))
    return out


def summarize(nodes):
    """国ごとに「問題の付いた商品が何件か」を数える (純関数)。"""
    from collections import Counter
    c = Counter()
    for nd in nodes:
        for country, _n in bad_sites(nd):
            c[country] += 1
    return c


# ── 通信 ────────────────────────────────────────────────────────────
def session():
    """保存した cookie を積んだ requests セッション。"""
    if not os.path.exists(COOKIE_FILE):
        raise SystemExit("cookie がありません。先に `python ebaymag_api.py --login` を。")
    s = requests.Session()
    for c in json.load(io.open(COOKIE_FILE, encoding="utf-8")):
        s.cookies.set(c["name"], c["value"],
                      domain=c.get("domain") or ".ebaymag.com", path=c.get("path") or "/")
    s.headers.update({"Content-Type": "application/json",
                      "Accept": "application/json",
                      "Origin": "https://ebaymag.com",
                      "Referer": "https://ebaymag.com/stock",
                      "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                     "AppleWebKit/537.36 (KHTML, like Gecko) "
                                     "Chrome/140.0.0.0 Safari/537.36")})
    # ★cookie だけでは通らない。画面が毎回付けている CSRF トークンが要る
    #   (無いと AUTHENTICITY_TOKEN_FAILURE)。ページから取り直せば済むので保存しない。
    s.headers["X-CSRF-Token"] = csrf_token(s)
    return s


def csrf_token(s):
    """画面の <meta name="csrf-token"> から取る。取れなければ止める。"""
    import re
    # ★HTML を返してもらう。session の既定は JSON なので、そのまま GET すると
    #   meta タグの無い応答が返って「作りが変わった」と誤診する (2026-09-06)。
    r = s.get("https://ebaymag.com/stock", timeout=60,
              headers={"Accept": "text/html,application/xhtml+xml",
                       "Content-Type": None})
    if r.status_code in (401, 403) or "/login" in r.url:
        raise SystemExit("ログインが切れています。`--login` でやり直してください。")
    m = re.search(r'name="csrf-token" content="([^"]+)"', r.text)
    if not m:
        raise SystemExit("CSRF トークンが読めませんでした (画面の作りが変わった可能性)")
    return m.group(1)


def call(s, operation, query, variables, tries=3):
    """GraphQL を1回叩く。失敗を黙って0件にしない。"""
    for i in range(tries):
        r = s.post(GQL, json={"operationName": operation, "variables": variables,
                              "query": query}, timeout=60)
        if r.status_code == 200:
            j = r.json()
            if j.get("errors"):
                raise SystemExit("GraphQL エラー: %s" % json.dumps(j["errors"],
                                                                  ensure_ascii=False)[:400])
            return j["data"]
        if r.status_code in (401, 403):
            raise SystemExit("ログインが切れています。`--login` でやり直してください。")
        time.sleep(2 * (i + 1))
    raise SystemExit("HTTP %s: %s" % (r.status_code, r.text[:300]))


def fetch_products(s, status=None, page=100):
    """商品を全部たどる。status='errors' でエラーのあるものだけ。"""
    out, after = [], None
    while True:
        f = dict(EMPTY_FILTER, status=status)
        d = call(s, "Products", PRODUCTS_QUERY,
                 {"first": page, "after": after, "filters": f})
        p = d["products"]
        out += p["nodes"]
        print("   %d件 …" % len(out))
        if not p["pageInfo"]["hasNextPage"]:
            return out
        after = p["pageInfo"]["endCursor"]


def do_login(seconds=600):
    """ブラウザを開いてログインを待ち、cookie を保存する (ここだけブラウザを使う)。"""
    import ebaymag_dump as E
    d = E.open_browser(headless=False)
    try:
        d.get(E.HOME)
        E.load_cookies(d)
        d.get(E.HOME)
        time.sleep(3)
        if E.looks_logged_out(d.current_url,
                              d.execute_script("return document.body.innerText;")):
            print("ブラウザで eBaymag にログインしてください。入れたら自動で進みます。")
            if not E.wait_for_login(d, seconds):
                print("⚠️ 時間内にログインを確認できませんでした")
                return 1
        n = E.save_cookies(d)
        print("[OK] cookie を %d本 保存しました → %s" % (n, COOKIE_FILE))
        print("     次からはブラウザは開きません。")
        return 0
    finally:
        try:
            d.quit()
        except Exception:                                         # noqa: BLE001
            pass


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                                             # noqa: BLE001
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--login", action="store_true", help="cookie を取り直す (ブラウザが開く)")
    ap.add_argument("--login-seconds", type=int, default=600)
    ap.add_argument("--errors", action="store_true", help="エラーのある商品を出す")
    ap.add_argument("--all", action="store_true", help="全商品を出す")
    ap.add_argument("--out", default=DESKTOP)
    a = ap.parse_args()

    if a.login:
        rc = do_login(a.login_seconds)
        if rc or not (a.errors or a.all):
            return rc

    if not (a.errors or a.all):
        print("--errors か --all を指定してください。")
        return 2

    s = session()
    status = "errors" if a.errors else None
    print("取得中 (%s) …" % (status or "全部"))
    nodes = fetch_products(s, status)
    print("合計 %d件" % len(nodes))

    c = summarize(nodes)
    print("--- 問題が付いているサイト ---")
    for country, n in c.most_common():
        print("   %-4s %d件" % (country, n))

    name = "ebaymag_%s_%s.csv" % ("errors" if a.errors else "all",
                                  time.strftime("%Y%m%d_%H%M%S"))
    p = os.path.join(a.out, name)
    with io.open(p, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["productId", "タイトル", "SKU", "在庫", "問題のあるサイト",
                    "配送ポリシーID", "出せていないサイト", "URL"])
        for nd in nodes:
            not_pub = [site_name((l_.get("site") or {}).get("id"))
                       for l_ in nd.get("listings") or []
                       if l_.get("selected") and not l_.get("published")]
            w.writerow([nd["id"], nd["title"],
                        ";".join((v.get("sku") or "") for v in nd.get("variations") or []),
                        nd.get("totalQuantity"),
                        ";".join("%s(%d)" % x for x in bad_sites(nd)),
                        nd.get("shippingProfileId"),
                        ";".join(not_pub), nd.get("url")])
    print("→", p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
