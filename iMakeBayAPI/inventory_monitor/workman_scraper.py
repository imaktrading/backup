"""workman_scraper - Workman 公式 商品ページ scraper (inventory_monitor 用 adapter).

HQ 実装 (workman_scraper_hq.fetch_workman_product、commit 63580d0、JSON-LD parse) を
inventory_monitor の他 scraper と同じ return schema に揃えるための薄い wrapper。

Workman は variation 別在庫情報なし (= JSON-LD は listing 全体の InStock/OutOfStock のみ)、
size dropdown はあるが在庫情報は size 別に取れない → **単独 listing 扱い** (= amazon と同 pattern):
  - 1 商品 1 SKU 1 qty 判定
  - listing level Revise (3 列 format、SKU 列なし) で qty=0 化 / qty=1 復活

使用例:
    from workman_scraper import fetch_product_inventory
    info = fetch_product_inventory("https://workman.jp/shop/g/g2300011882014/")
    # → {"name": ..., "color": ..., "skus": [{"size": "", "in_stock": True, ...}]}
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from workman_scraper_hq import fetch_workman_product  # noqa: E402


def fetch_product_inventory(url: str) -> Optional[dict]:
    """Workman 商品 URL → inventory_monitor 標準 schema.

    Returns: {
        "name": "<日本語商品名>",
        "color": "<カタカナ>",
        "product_id": "<13桁 mpn>",
        "skus": [
            {"size": "", "communication_code": "<mpn>",
             "in_stock": bool, "stock_status": "InStock"/"OutOfStock",
             "quantity": 1 or 0, "price_jpy": int, ...}
        ],
    } or None on failure.
    """
    raw = fetch_workman_product(url)
    if not raw:
        return None

    in_stock = (raw.get("availability") or "").lower() == "instock"
    mpn = raw.get("mpn", "")
    return {
        "name": raw.get("name", ""),
        "color": raw.get("color", ""),
        "product_id": mpn,
        "skus": [
            {
                "size": "",
                "size_display_code": "",
                "communication_code": mpn,
                "l2Id": mpn,
                "in_stock": in_stock,
                "stock_status": "InStock" if in_stock else "OutOfStock",
                "stock_label": "在庫あり" if in_stock else "在庫なし",
                "quantity": 1 if in_stock else 0,
                "price_jpy": raw.get("price_jpy", 0),
                "promo_price_jpy": raw.get("price_jpy", 0),
                "sales_active": in_stock,
            }
        ],
        "raw_workman": raw,
    }


if __name__ == "__main__":
    import argparse
    import json
    parser = argparse.ArgumentParser(description="Workman 商品在庫取得 (inventory_monitor adapter)")
    parser.add_argument("url")
    args = parser.parse_args()
    info = fetch_product_inventory(args.url)
    if not info:
        print("取得失敗")
        sys.exit(1)
    info = {k: v for k, v in info.items() if k != "raw_workman"}
    print(json.dumps(info, ensure_ascii=False, indent=2))
