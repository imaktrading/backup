# -*- coding: utf-8 -*-
"""eBay Business Policies Management API で Shipping Policy 一括作成
- API: SellerProfilesManagementService (SOAP)
- 認証: 既存 AuthToken (Trading API)
- まずテスト 1 個作成、動作OK なら 93 個一括

エンドポイント (Production):
  https://svcs.ebay.com/services/selling/v1/SellerProfilesManagementService

注意:
  - Business Policies Management API は Deprecated だが動作中
  - 長期的には REST Account API への移行推奨
"""
import requests
from pathlib import Path

KEYS_FILE = Path(r"c:\dev\iMak\iMakeBayAPI\ebay keys.txt")
ENDPOINT = "https://svcs.ebay.com/services/selling/v1/SellerProfilesManagementService"


def load_keys():
    keys = {}
    with open(KEYS_FILE, "r") as f:
        for line in f:
            if "=" in line:
                k, v = line.strip().split("=", 1)
                keys[k.strip()] = v.strip()
    return keys


def add_shipping_policy(name: str, desc: str, cost_usd: float, auth_token: str,
                       service: str = "OtherInternational",
                       ship_time_min: int = 10, ship_time_max: int = 20) -> requests.Response:
    """1 個の Shipping Policy を作成"""
    headers = {
        "X-EBAY-SOA-OPERATION-NAME": "addSellerProfile",
        "X-EBAY-SOA-SECURITY-TOKEN": auth_token,
        "X-EBAY-SOA-GLOBAL-ID": "EBAY-US",
        "X-EBAY-SOA-SERVICE-NAME": "SellerProfilesManagementService",
        "X-EBAY-SOA-REQUEST-DATA-FORMAT": "XML",
        "Content-Type": "text/xml",
    }
    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<addSellerProfileRequest xmlns="http://www.ebay.com/marketplace/selling">
  <profile>
    <profileName>{name}</profileName>
    <profileDesc>{desc}</profileDesc>
    <profileType>SHIPPING</profileType>
    <profileVersion>0</profileVersion>
    <shippingPolicyInfo>
      <ShippingPolicyInfoFlatRate>
        <InternationalShippingServiceCostList>
          <InternationalShippingServiceCost>
            <ShippingService>{service}</ShippingService>
            <ShippingCost currencyID="USD">{cost_usd:.2f}</ShippingCost>
            <ShipToLocation>Worldwide</ShipToLocation>
            <ShippingTimeMin>{ship_time_min}</ShippingTimeMin>
            <ShippingTimeMax>{ship_time_max}</ShippingTimeMax>
          </InternationalShippingServiceCost>
        </InternationalShippingServiceCostList>
        <ShippingPolicyType>FLAT</ShippingPolicyType>
      </ShippingPolicyInfoFlatRate>
      <DispatchTimeMax>3</DispatchTimeMax>
    </shippingPolicyInfo>
  </profile>
</addSellerProfileRequest>"""
    return requests.post(ENDPOINT, headers=headers, data=xml.encode("utf-8"))


def generate_policies_definitions():
    """93 Policy の定義 (段階ピッチ + 3 グループ + +5%バッファ)"""
    # 段階価格帯 (上限基準)
    bins = [
        (10, 10), (20, 20), (30, 30), (40, 40), (50, 50), (60, 60), (70, 70), (80, 80), (90, 90), (100, 100),  # $10刻み
        (120, 120), (140, 140), (160, 160), (180, 180), (200, 200), (220, 220), (240, 240), (260, 260), (280, 280), (300, 300),  # $20刻み
        (350, 350), (400, 400), (450, 450), (500, 500), (550, 550), (600, 600),  # $50刻み
        (700, 700), (800, 800), (900, 900), (1000, 1000),  # $100刻み
        (1500, 1500),
    ]
    # グループ別 hts_rate (+5%バッファ込み)
    groups = {
        "A": 0.18,  # 低関税 (= 0.13 + 5%)
        "B": 0.30,  # 中関税
        "C": 0.43,  # 高関税
    }
    policies = []
    for group_id, rate in groups.items():
        for i, (label_upper, calc_upper) in enumerate(bins, 1):
            cost = calc_upper * rate * 1.021 + 1.5
            name = f"DDP-{group_id}-P{i:02d}"
            desc = f"DDP G{group_id} ≤${label_upper} (rate {rate:.2f})"
            policies.append({"name": name, "desc": desc, "cost": round(cost, 2)})
    return policies


def main():
    keys = load_keys()
    auth_token = keys["AuthToken"]

    # ===== Step 1: テスト Policy 1 個 作成 =====
    test_policy = {
        "name": "TEST-DDP-A-P01",
        "desc": "テスト用、低関税 ≤$10",
        "cost": 3.34,  # 10 × 0.18 × 1.021 + 1.5
    }
    print(f"[test] {test_policy['name']} 作成: ${test_policy['cost']}")
    resp = add_shipping_policy(test_policy["name"], test_policy["desc"], test_policy["cost"], auth_token)
    print(f"  status: {resp.status_code}")
    print(f"  response (先頭500文字):")
    print(f"  {resp.text[:500]}")

    # 成功確認後に一括作成へ
    print()
    print("=" * 60)
    print("テスト動作確認後、policies = generate_policies_definitions() で 93 個一括作成可能")
    policies = generate_policies_definitions()
    print(f"全 Policy 数: {len(policies)}")
    print("先頭 5 件:")
    for p in policies[:5]:
        print(f"  {p['name']:20} | ${p['cost']:>7.2f} | {p['desc']}")


if __name__ == "__main__":
    main()
