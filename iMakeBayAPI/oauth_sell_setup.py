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

# Windows の既定 stdout(cp932) だと ✅ 等の絵文字 print で UnicodeEncodeError → utf-8 化。
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
KEYS_FILE = os.path.join(SCRIPT_DIR, "ebay keys.txt")
SELL_TOKEN_FILE = os.path.join(SCRIPT_DIR, "ebay_oauth_token_sell.json")

# ★2026-08-21: 鍵を共有領域にも置いた (他 worktree から使うため)。
#   トークンは使うたびに更新されるので、**2か所に置いたまま片方だけ更新されると腐る**
#   (今日1日はまった「同じものが2か所にあって片方だけ直る」と同じ形)。
#   書き手はこのファイルだけなので、**書いたら必ず両方に同じ内容を置く**。
SHARED_DIR = r"C:/dev/iMak_data/credentials"


def save_token(tok):
    """トークンを保存する。**共有側にも必ず同じ内容を書く** (片方だけ新しくしない)。"""
    for path in (SELL_TOKEN_FILE, os.path.join(SHARED_DIR, "ebay_oauth_token_sell.json")):
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(tok, f, ensure_ascii=False, indent=2)
        except Exception as e:                                 # noqa: BLE001
            # 共有側に書けなくても本体の更新は止めない。ただし黙らない
            print("⚠️ トークンを保存できませんでした: %s (%s)" % (path, e))

OAUTH_AUTHORIZE = "https://auth.ebay.com/oauth2/authorize"
OAUTH_TOKEN = "https://api.ebay.com/identity/v1/oauth2/token"

# Trading 互換のため基本 scope も併せて要求（superset）。
SCOPES = [
    "https://api.ebay.com/oauth/api_scope",
    "https://api.ebay.com/oauth/api_scope/sell.analytics.readonly",
    "https://api.ebay.com/oauth/api_scope/sell.fulfillment.readonly",
    # 2026-07-02: Business Policy(配送ポリシー)の状態を Account API で読むため追加。
    # Trading GetSellerProfiles は廃止済 → sell/account/v1/fulfillment_policy が唯一の read 経路。
    # 2026-07-05: SpeedPAK化(国際便をStandardInternational→SpeedPAK)を API で書換えるため
    # readonly → write の sell.account に昇格(read も兼ねる)。
    "https://api.ebay.com/oauth/api_scope/sell.account",
    # 2026-07-06: eBaymag出品の inline 配送を ReviseItem(Trading, IAFトークン)で SpeedPAK に
    # 書換えるため sell.inventory 追加。
    "https://api.ebay.com/oauth/api_scope/sell.inventory",
    # 2026-08-14: 広告 (Promoted Listings) のキャンペーンと、そこに入っている商品を
    # API で読むため追加。画面では「どの出品が広告に入っていないか」を追えない
    # (キャンペーン7本で計 1,700件 / 出品総数はそれより多い)。**読取のみ**。
    "https://api.ebay.com/oauth/api_scope/sell.marketing.readonly",
    # 2026-08-18: 入稿後に手でやっていた「プロモを8%に」を API でやるため **書込**を追加。
    #   readonly のままだと ad rate を設定できない (実測: refresh grant に write scope を
    #   要求すると invalid_scope が返る = 未同意)。read も兼ねるが、既存の readonly は
    #   他ツール (ads_coverage) の前提なので消さずに併記する。
    "https://api.ebay.com/oauth/api_scope/sell.marketing",
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
    save_token(tok)
    print("✅ 保存:", SELL_TOKEN_FILE, "+ 共有領域")
    print("scope:", tok.get("scope", "(なし)"))
    print("refresh 有効期限(s):", tok.get("refresh_token_expires_in"))


def cmd_refresh(args):
    app_id, app_secret = load_keys()
    if not os.path.exists(SELL_TOKEN_FILE):
        sys.exit("先に exchange で token を取得してください。")
    tok = json.load(open(SELL_TOKEN_FILE, encoding="utf-8"))
    # ★2026-08-14: refresh に送るのは **実際に同意済みの scope** (token 自身が持っている値)。
    #   SCOPES を直接送ると、コード側に scope を1つ足した瞬間に「まだ同意していない権限」を
    #   要求する形になり、**再同意を済ませるまで refresh が全部 500/invalid_scope で落ちる**。
    #   refresh は eBaymag 配送書換え等の稼働経路が2時間ごとに使うので、そこを道連れにしない。
    granted = (tok.get("scope") or "").strip() or " ".join(SCOPES)
    resp = requests.post(
        OAUTH_TOKEN,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Basic {basic_auth(app_id, app_secret)}",
        },
        data={
            "grant_type": "refresh_token",
            "refresh_token": tok["refresh_token"],
            "scope": granted,
        },
        timeout=20,
    )
    if resp.status_code != 200:
        print("FAILED:", resp.status_code, resp.text)
        sys.exit(1)
    new = resp.json()
    tok["access_token"] = new["access_token"]
    tok["expires_in"] = new.get("expires_in")
    save_token(tok)
    print("✅ access_token 更新済 (共有領域にも保存)")


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
