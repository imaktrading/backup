"""workman_scraper - ワークマン公式商品ページから JSON-LD 経由で商品データ抽出.

5/16 ユーザー判断: HQ 完結で実装 (= 各 worker への分配は後回し)。
ワークマン公式 (https://workman.jp/shop/g/g<13桁>/) は JSON-LD で Product schema
を埋込済なので、requests + parse で取得可。Selenium / Vision 不要。

取得項目:
  - name (商品名、日本語)
  - mpn (= 13 桁商品コード)
  - image (サムネ URL、_t1 → _l1 で高解像度)
  - color (カタカナ単独、Vision 不要)
  - price (整数 JPY)
  - availability (InStock / OutOfStock)
  - releaseDate
  - brand
"""
from __future__ import annotations

import json
import re
import sys
from typing import Optional

import requests

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/136.0.0.0 Safari/537.36"),
    "Accept-Language": "ja-JP,ja;q=0.9",
}


def fetch_workman_product(url: str, timeout: int = 15) -> Optional[dict]:
    """Workman 商品ページから product dict 取得.

    Returns: {
        "url": <url>, "mpn": "<13桁>", "name": "<title>",
        "color": "<カタカナ>", "price_jpy": <int>,
        "availability": "InStock"/"OutOfStock", "release_date": "YYYY/MM/DD",
        "image_url": "<low res>", "image_url_hi": "<high res>",
        "brand": "<ワークマン系>", "sizes": [<size list、要scraping>],
        "raw_json_ld": <dict>,
    } or None if 取得失敗.
    """
    try:
        r = requests.get(url, headers=_HEADERS, timeout=timeout)
        if r.status_code != 200:
            return None
        html = r.text
    except Exception:
        return None

    m = re.search(r'<script[^>]*application/ld\+json[^>]*>(.+?)</script>',
                   html, re.S)
    if not m:
        return None
    try:
        ld = json.loads(m.group(1))
    except Exception:
        return None

    if isinstance(ld, list):
        ld = next((x for x in ld if x.get("@type") == "Product"), ld[0])
    if not isinstance(ld, dict) or ld.get("@type") != "Product":
        return None

    offers = ld.get("offers") or {}
    brand = ld.get("brand") or {}
    image = ld.get("image") or ""
    # high res: _t1 → _l1
    image_hi = image.replace("/img/goods/S/", "/img/goods/L/").replace("_t1.", "_l1.") if image else ""

    # size list: HTML 内 size dropdown から抽出
    sizes = []
    for s_m in re.finditer(r'data-size[^=]*="([^"]+)"', html):
        s = s_m.group(1).strip()
        if s and s not in sizes and len(s) <= 8:
            sizes.append(s)
    if not sizes:
        # 別 pattern: <option value="..."> 内に S/M/L 等
        for s_m in re.finditer(r'<option[^>]*>(XS|S|M|L|XL|XXL|3L|4L|3XL)[^<]{0,5}</option>', html):
            s = s_m.group(1)
            if s not in sizes:
                sizes.append(s)

    return {
        "url": url,
        "mpn": ld.get("mpn", ""),
        "name": ld.get("name", ""),
        "color": ld.get("color", ""),
        "price_jpy": int(offers.get("price", 0)) if offers.get("price") else 0,
        "availability": (offers.get("availability") or "").split("/")[-1],
        "release_date": ld.get("releaseDate", ""),
        "image_url": image,
        "image_url_hi": image_hi,
        "brand": brand.get("name", "") if isinstance(brand, dict) else str(brand),
        "sizes": sizes,
        "raw_json_ld": ld,
    }


def is_workman_url(url: str) -> bool:
    """Workman 公式 URL 判定."""
    return bool(url and "workman.jp/shop/g/" in url)


def extract_sku_from_workman_url(url: str) -> str:
    """Workman URL から SKU (= mpn) 抽出. 例: /shop/g/g2300011882014/ → 2300011882014."""
    m = re.search(r"/g/g(\d{10,15})", url or "")
    return m.group(1) if m else ""


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("url", help="Workman 商品 URL")
    args = parser.parse_args()
    d = fetch_workman_product(args.url)
    if d:
        # raw_json_ld 除いて整形表示
        d2 = {k: v for k, v in d.items() if k != "raw_json_ld"}
        print(json.dumps(d2, ensure_ascii=False, indent=2))
    else:
        print("取得失敗")
        sys.exit(1)
