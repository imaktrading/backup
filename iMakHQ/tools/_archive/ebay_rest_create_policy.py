# -*- coding: utf-8 -*-
"""eBay REST Account API で Fulfillment Policy 作成 (テスト 1 個)"""
import requests
import json
from pathlib import Path

TOKEN_FILE = Path(r"c:\dev\iMak\iMakeBayAPI\ebay_oauth_token.json")

# Token 読み込み
token_data = json.loads(TOKEN_FILE.read_text(encoding="utf-8-sig"))
access_token = token_data["access_token"]

# Policy 作成 (TEST-DDP-A-P01)
url = "https://api.ebay.com/sell/account/v1/fulfillment_policy"
headers = {
    "Authorization": f"Bearer {access_token}",
    "Content-Type": "application/json",
    "Accept": "application/json",
    "Content-Language": "en-US",
}

body = {
    "name": "TEST-DDP-A-P01",
    "description": "テスト V6 低関税 <=$10",
    "marketplaceId": "EBAY_US",
    "categoryTypes": [{"name": "ALL_EXCLUDING_MOTORS_VEHICLES", "default": True}],
    "handlingTime": {"value": 3, "unit": "DAY"},
    "shippingOptions": [
        {
            "optionType": "INTERNATIONAL",
            "costType": "FLAT_RATE",
            "shippingServices": [
                {
                    "shippingCarrierCode": "Other",
                    "shippingServiceCode": "OtherInternational",
                    "shipToLocations": {
                        "regionIncluded": [{"regionName": "Worldwide"}]
                    },
                    "shippingCost": {"value": "3.34", "currency": "USD"},
                    "freeShipping": False,
                    "sortOrder": 1,
                }
            ],
        }
    ],
}

resp = requests.post(url, headers=headers, json=body)
print(f"Status: {resp.status_code}")
print(f"Response:")
print(resp.text)

if resp.status_code in [200, 201]:
    print("\n✓ TEST-DDP-A-P01 作成成功!")
