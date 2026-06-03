#!/usr/bin/env python3
"""
eBay Sell REST API 用 User Access Token 取得ヘルパー (authorization_code flow)

目的:
  Analytics API (getTrafficReport) / Fulfillment API (getOrders) は
  sell.analytics.readonly / sell.fulfillment.readonly scope 付きの
  User Access Token が必須。既存 ebay_oauth_token.json (Trading 用) は
  scope='' で叩けないため、追加 scope 付きで一度だけ再同意して取得する。

安全設計:
  - 既存 Trading token (ebay_oauth_token.json) は **触らない**（稼働中の監視くんを壊さない）。
  - 取得結果は **別ファイル** ebay_oauth_token_sell.json に保存。
  - App 認証情報は "ebay keys.txt" (AppID/AppSecret) から読む（ハードコードしない）。

使い方:
  1) python oauth_sell_setup.py url --runame "<RuName>"
       → ブラウザで開く同意 URL を表示。eBay にログイン+同意。
  2) リダイレクト先 URL の ?code=... をコピー
  3) python oauth_sell_setup.py exchange --runame "<RuName>" --code "<code>"
       → access_token + refresh_token を ebay_oauth_token_sell.json に保存
  4) python oauth_sell_setup.py refresh
       → 以後の access_token 更新（refresh_token は ~18ヶ月有効）
"""
import argparse
import base64
import json
import os
import sys
import urllib.parse

import requests

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
KEYS_FILE = os.path.join(SCRIPT_DIR, "ebay keys.txt")
SELL_TOKEN_FILE = os.path.join(SCRIPT_DIR, "ebay_oauth_token_sell.json")

OAUTH_AUTHORIZE = "https://auth.ebay.com/oauth2/authorize"
OAUTH_TOKEN = "https://api.ebay.com/identity/v1/oauth2/token"

# Trading 互換のため基本 scope も併せて要求（superset）。
SCOPES = [
    "https://api.ebay.com/oauth/api_scope",
    "https://api.ebay.com/oauth/api_scope/sell.analytics.readonly",
    "https://api.ebay.com/oauth/api_scope/sell.fulfillment.readonly",
]


def load_keys():
    keys = {}
    with open(KEYS_FILE, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if "=" in line:
                k, v = line.split("=", 1)
                keys[k.strip()] = v.strip()
    app_id = keys.get("AppID")
    app_secret = keys.get("AppSecret")
    if not app_id or not app_secret:
        sys.exit("AppID / AppSecret が 'ebay keys.txt' に見つかりません。")
    return app_id, app_secret


def basic_auth(app_id, app_secret):
    return base64.b64encode(f"{app_id}:{app_secret}".encode()).decode()


def cmd_url(args):
    app_id, _ = load_keys()
    params = {
        "client_id": app_id,
        "response_type": "code",
        "redirect_uri": args.runame,
        "scope": " ".join(SCOPES),
        "prompt": "login",
    }
    url = OAUTH_AUTHORIZE + "?" + urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
    print("\n=== ① 下記 URL をブラウザで開いて eBay にログイン+同意 ===\n")
    print(url)
    print("\n=== ② 同意後にリダイレクトされた URL の ?code=... 部分をコピー ===")
    print("（code は URL エンコード済・5分で失効。コピーしたらすぐ exchange）\n")


def cmd_exchange(args):
    app_id, app_secret = load_keys()
    # code は URL エンコードされていることがあるので decode してから渡す
    code = urllib.parse.unquote(args.code)
    resp = requests.post(
        OAUTH_TOKEN,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Basic {basic_auth(app_id, app_secret)}",
        },
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": args.runame,
        },
        timeout=20,
    )
    if resp.status_code != 200:
        print("FAILED:", resp.status_code)
        print(resp.text)
        sys.exit(1)
    tok = resp.json()
    with open(SELL_TOKEN_FILE, "w", encoding="utf-8") as f:
        json.dump(tok, f, ensure_ascii=False, indent=2)
    print("✅ 保存:", SELL_TOKEN_FILE)
    print("scope:", tok.get("scope", "(なし)"))
    print("refresh 有効期限(s):", tok.get("refresh_token_expires_in"))


def cmd_refresh(args):
    app_id, app_secret = load_keys()
    if not os.path.exists(SELL_TOKEN_FILE):
        sys.exit("先に exchange で token を取得してください。")
    tok = json.load(open(SELL_TOKEN_FILE, encoding="utf-8"))
    resp = requests.post(
        OAUTH_TOKEN,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Basic {basic_auth(app_id, app_secret)}",
        },
        data={
            "grant_type": "refresh_token",
            "refresh_token": tok["refresh_token"],
            "scope": " ".join(SCOPES),
        },
        timeout=20,
    )
    if resp.status_code != 200:
        print("FAILED:", resp.status_code, resp.text)
        sys.exit(1)
    new = resp.json()
    tok["access_token"] = new["access_token"]
    tok["expires_in"] = new.get("expires_in")
    with open(SELL_TOKEN_FILE, "w", encoding="utf-8") as f:
        json.dump(tok, f, ensure_ascii=False, indent=2)
    print("✅ access_token 更新済")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p1 = sub.add_parser("url"); p1.add_argument("--runame", required=True)
    p2 = sub.add_parser("exchange"); p2.add_argument("--runame", required=True); p2.add_argument("--code", required=True)
    sub.add_parser("refresh")
    args = ap.parse_args()
    {"url": cmd_url, "exchange": cmd_exchange, "refresh": cmd_refresh}[args.cmd](args)


if __name__ == "__main__":
    main()
