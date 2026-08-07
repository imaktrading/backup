# -*- coding: utf-8 -*-
"""eBay OAuth Consent URL 生成
ユーザーが Browser でこの URL を開いてログイン → 認可
→ Redirect 後の URL バーから authorization_code を取得
"""
from pathlib import Path
from urllib.parse import urlencode

KEYS_FILE = Path(r"c:\dev\iMak\iMakeBayAPI\ebay keys.txt")
RUNAME = "Takaaki_Kami-TakaakiK-ecesar-dnxlk"

keys = {}
with open(KEYS_FILE, "r") as f:
    for line in f:
        if "=" in line:
            k, v = line.strip().split("=", 1)
            keys[k.strip()] = v.strip()

app_id = keys["AppID"]

# Sell Account scope (Business Policy 操作用)
# scope は単一にしてシンプル化
scopes = "https://api.ebay.com/oauth/api_scope/sell.account"

params = {
    "client_id": app_id,
    "response_type": "code",
    "redirect_uri": RUNAME,
    "scope": scopes,
}

url = "https://auth.ebay.com/oauth2/authorize?" + urlencode(params)

print("=" * 60)
print("eBay OAuth Consent URL")
print("=" * 60)
print()
print("以下の URL を Browser で開いてください:")
print()
print(url)
print()
print("=" * 60)
print("操作手順:")
print("=" * 60)
print("1. 上記 URL を Browser に貼り付け")
print("2. eBay ログイン (= 売り手アカウント)")
print("3. 認可画面で「同意」")
print("4. Redirect 後、URL バーに 'code=XXXXX' が出る")
print("   (= localhost で接続失敗するが、URL は valid)")
print("5. URL バーの code= 以降の文字列をコピーして Claude に渡す")
