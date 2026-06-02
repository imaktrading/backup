# -*- coding: utf-8 -*-
"""eBay OAuth authorization_code → access_token + refresh_token 交換"""
import requests
import base64
import json
from pathlib import Path
from urllib.parse import unquote

KEYS_FILE = Path(r"c:\dev\iMak\iMakeBayAPI\ebay keys.txt")
TOKEN_FILE = Path(r"c:\dev\iMak\iMakeBayAPI\ebay_oauth_token.json")
RUNAME = "Takaaki_Kami-TakaakiK-ecsear-dnxtk"

# authorization_code (URL エンコード済) → デコード
AUTH_CODE_ENCODED = "v%5E1.1%23i%5E1%23r%5E1%23I%5E3%23p%5E3%23f%5E0%23t%5EUl41XzA6MDgxMUM1OUZDNzEwN0UxNTcyQTdBMjAzOUQ1OTc4QTZfMl8xI0VeMjYw"
auth_code = unquote(AUTH_CODE_ENCODED)

keys = {}
with open(KEYS_FILE, "r") as f:
    for line in f:
        if "=" in line:
            k, v = line.strip().split("=", 1)
            keys[k.strip()] = v.strip()

app_id = keys["AppID"]
app_secret = keys["AppSecret"]

credentials = base64.b64encode(f"{app_id}:{app_secret}".encode()).decode()

resp = requests.post(
    "https://api.ebay.com/identity/v1/oauth2/token",
    headers={
        "Content-Type": "application/x-www-form-urlencoded",
        "Authorization": f"Basic {credentials}",
    },
    data={
        "grant_type": "authorization_code",
        "code": auth_code,
        "redirect_uri": RUNAME,
    },
)

print(f"Status: {resp.status_code}")
print(f"Response:")
print(resp.text)

if resp.status_code == 200:
    data = resp.json()
    # token 保存
    TOKEN_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    print(f"\n[saved] {TOKEN_FILE}")
    print(f"  access_token (expires in {data.get('expires_in')}s)")
    print(f"  refresh_token (expires in {data.get('refresh_token_expires_in')}s)")
