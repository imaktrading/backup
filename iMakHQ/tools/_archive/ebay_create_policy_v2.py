# -*- coding: utf-8 -*-
"""eBay AddSellerProfile (修正版): 必須フィールド完全版"""
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

headers = {
    "X-EBAY-SOA-OPERATION-NAME": "addSellerProfile",
    "X-EBAY-SOA-SECURITY-TOKEN": auth_token,
    "X-EBAY-SOA-GLOBAL-ID": "EBAY-US",
    "X-EBAY-SOA-SERVICE-NAME": "SellerProfilesManagementService",
    "X-EBAY-SOA-REQUEST-DATA-FORMAT": "XML",
    "Content-Type": "text/xml",
}

# 必須フィールド完全版
xml = """<?xml version="1.0" encoding="utf-8"?>
<addSellerProfileRequest xmlns="http://www.ebay.com/marketplace/selling">
  <profile>
    <profileName>TEST-DDP-A-P01</profileName>
    <profileDesc>テスト V6 低関税 less10</profileDesc>
    <profileType>SHIPPING</profileType>
    <profileVersion>0</profileVersion>
    <categoryGroups>
      <categoryGroup>
        <name>ALL</name>
        <default>true</default>
      </categoryGroup>
    </categoryGroups>
    <shippingPolicyInfo>
      <shippingPolicyName>TEST-DDP-A-P01</shippingPolicyName>
      <domesticShippingType>NotOffered</domesticShippingType>
      <intlShippingType>Flat</intlShippingType>
      <dispatchTimeMax>3</dispatchTimeMax>
      <intlShippingPolicyInfoService>
        <shippingService>OtherInternational</shippingService>
        <shippingServiceCost currencyID="USD">3.34</shippingServiceCost>
        <shippingServicePriority>1</shippingServicePriority>
        <shipToLocation>Worldwide</shipToLocation>
      </intlShippingPolicyInfoService>
    </shippingPolicyInfo>
  </profile>
</addSellerProfileRequest>"""

resp = requests.post(ENDPOINT, headers=headers, data=xml.encode("utf-8"))
print(f"Status: {resp.status_code}")
print(f"Response 全文:")
print(resp.text)
