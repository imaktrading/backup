# -*- coding: utf-8 -*-
"""eBay GetSellerProfiles で既存 Shipping Policy 一覧を確認"""
import requests
from pathlib import Path

KEYS_FILE = Path(r"c:\dev\iMak\iMakeBayAPI\ebay keys.txt")
ENDPOINT = "https://svcs.ebay.com/services/selling/v1/SellerProfilesManagementService"

keys = {}
with open(KEYS_FILE, "r") as f:
    for line in f:
        if "=" in line:
            k, v = line.strip().split("=", 1)
            keys[k.strip()] = v.strip()
auth_token = keys["AuthToken"]

# GetSellerProfiles で一覧取得
headers = {
    "X-EBAY-SOA-OPERATION-NAME": "getSellerProfiles",
    "X-EBAY-SOA-SECURITY-TOKEN": auth_token,
    "X-EBAY-SOA-GLOBAL-ID": "EBAY-US",
    "X-EBAY-SOA-SERVICE-NAME": "SellerProfilesManagementService",
    "X-EBAY-SOA-REQUEST-DATA-FORMAT": "XML",
    "Content-Type": "text/xml",
}
xml = """<?xml version="1.0" encoding="utf-8"?>
<getSellerProfilesRequest xmlns="http://www.ebay.com/marketplace/selling">
</getSellerProfilesRequest>"""

resp = requests.post(ENDPOINT, headers=headers, data=xml.encode("utf-8"))
print(f"Status: {resp.status_code}")
print(f"Response 全文:")
print(resp.text[:5000])
