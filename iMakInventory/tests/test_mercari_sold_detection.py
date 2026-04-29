"""mercari_scraper sold-detection regression test.

2026-04-29 false-negative バグ修正の固定化:
  - checkout-button は売切ページでも DOM に残る
  - 修正前: testid 存在で in_stock 判定 → false negative 9 件発覚
  - 修正後: button text "売り切れました" / disabled class / name=disabled
           で売切判定する

このテストは Live Mercari URL を叩く (ネットワーク必須)。
通常 CI からは除外、運用前ローカル smoke 用。
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

# parent path 確保 (iMakInventory ルート)
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scrapers.mercari_scraper import fetch_product_inventory, create_driver  # noqa: E402


# Takaaki さん目視確認: いずれも実際売切 (TEST_HIGH 9件)
KNOWN_SOLD_URLS = [
    ("row6",   "https://jp.mercari.com/item/m81334162487"),
    ("row85",  "https://jp.mercari.com/item/m89212781202"),
    ("row87",  "https://jp.mercari.com/item/m86631907186"),
    ("row88",  "https://jp.mercari.com/item/m36837780005"),
    ("row118", "https://jp.mercari.com/item/m14968932238"),
    ("row127", "https://jp.mercari.com/item/m84213071035"),
    ("row128", "https://jp.mercari.com/item/m34247662912"),
    ("row129", "https://jp.mercari.com/item/m83933181328"),
    ("row131", "https://jp.mercari.com/item/m61680512158"),
]


def main():
    print(f"=== mercari_scraper sold-detection regression test ({len(KNOWN_SOLD_URLS)} URLs) ===")
    driver = create_driver(headless=True)
    failures = []
    try:
        for label, url in KNOWN_SOLD_URLS:
            print(f"\n[{label}] {url}")
            info = fetch_product_inventory(url, driver=driver, use_selenium_fallback=False)
            if info is None:
                print(f"  ⚠️ scraper returned None (fail-closed)")
                failures.append((label, "None", url))
                continue
            sku = info["skus"][0]
            in_stock = sku["in_stock"]
            print(f"  status={info['status']:>10}  in_stock={in_stock}  name='{info['name'][:40]}'")
            # 期待: in_stock=False (= sold)
            if in_stock:
                print(f"  ❌ FAIL: 売切のはずが in_stock=True 判定 (false negative)")
                failures.append((label, "false_negative", url))
            else:
                print(f"  ✅ OK: 正しく sold 判定")
    finally:
        try:
            driver.quit()
        except Exception:
            pass

    print()
    print(f"=== 結果: {len(KNOWN_SOLD_URLS) - len(failures)}/{len(KNOWN_SOLD_URLS)} passed ===")
    if failures:
        print("失敗:")
        for label, reason, url in failures:
            print(f"  [{label}] {reason}: {url}")
        sys.exit(1)
    print("✅ 全件 sold 検出に成功 (false-negative バグ解消)")


if __name__ == "__main__":
    main()
