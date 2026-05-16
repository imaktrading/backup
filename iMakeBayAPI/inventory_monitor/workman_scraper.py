"""workman_scraper - Workman 公式 商品 variation 在庫 scraper (Phase 2).

Phase 2 (2026-05-16): Workman variation 化対応。AJAX endpoint
`POST /shop/goods/ajaxgoodsstock.aspx` で 1 回呼出 = 全 variation 取得。
Selenium 不要、HTTP-only。

Phase 1 (commit edad2e0、JSON-LD parse、1 listing=1 SKU 設計) からの変更:
- workman_scraper_hq (JSON-LD parse) は商品名/価格取得用に使用継続
- AJAX 経路で variation matrix (color × size) を取得
- inventory_monitor 標準 schema (skus list に N variation) で return

AJAX response 構造:
- color list: `<dl class="block-color--item ...">` title="<color_jp>"
- size matrix: `<div class="block-select-size-detail--item block-pattern (no-stock|...)">`
  - 並び順: color1.size1, color1.size2, ..., color2.size1, ...
  - 各 size block に sku_mpn (= backorder.aspx?goods=<mpn> or input goods= or sku=<mpn> から抽出)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Optional

import requests

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from workman_scraper_hq import fetch_workman_product  # noqa: E402

AJAX_URL = "https://workman.jp/shop/goods/ajaxgoodsstock.aspx"
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/136.0.0.0 Safari/537.36"),
    "Accept-Language": "ja-JP,ja;q=0.9",
    "Content-Type": "application/x-www-form-urlencoded",
}
TIMEOUT_SEC = 15

# 全角サイズ → 半角正規化
_SIZE_MAP = {
    "Ｓ": "S", "Ｍ": "M", "Ｌ": "L", "ＬＬ": "LL", "ＸＳ": "XS",
    "ＸＬ": "XL", "ＸＸＬ": "XXL", "ＸＸＸＬ": "XXXL",
    "３Ｌ": "3L", "４Ｌ": "4L", "５Ｌ": "5L", "６Ｌ": "6L",
}


def _normalize_size(jp: str) -> str:
    """全角 → 半角 size 表記。"""
    s = (jp or "").strip()
    return _SIZE_MAP.get(s, s)


def _extract_parent_mpn(url: str) -> str:
    """URL から parent_mpn (= 13桁) 抽出. 例: /shop/g/g2300067335038/ → 2300067335038."""
    m = re.search(r"/g/g(\d{10,15})", url or "")
    return m.group(1) if m else ""


def fetch_variations_via_ajax(parent_mpn: str) -> Optional[dict]:
    """AJAX endpoint で variation matrix 取得.

    Returns: {
        "colors": [{"name": "<color_jp>", "enabled": bool, "image": "<path>"}, ...],
        "sizes_per_color": [{"color_jp": "...", "variants": [
            {"size_jp": "Ｓ", "size_normalized": "S", "variant_sku_mpn": "...",
             "in_stock": bool}, ...
        ]}, ...]
    } or None on failure.
    """
    if not parent_mpn:
        return None
    try:
        from bs4 import BeautifulSoup  # noqa: PLC0415
    except ImportError:
        # bs4 不在環境: 簡易 regex parse (= fallback、精度低)
        return _fetch_via_regex(parent_mpn)

    try:
        r = requests.post(AJAX_URL, headers=HEADERS,
                          data={"goods": parent_mpn}, timeout=TIMEOUT_SEC)
        if r.status_code != 200:
            return None
        html = r.text
    except Exception:
        return None

    soup = BeautifulSoup(html, "html.parser")

    # color list 抽出
    colors = []
    for dl in soup.select(".block-color--item"):
        title = (dl.get("title", "") or "").strip()
        cls = " ".join(dl.get("class", []))
        img = dl.select_one("img")
        img_src = img.get("src", "") if img else ""
        colors.append({
            "name": title,
            "enabled": "enable-stock" in cls,
            "image": img_src,
        })

    # size matrix 抽出
    size_blocks = soup.select(".block-select-size-detail--item")
    all_variants = []
    for sb in size_blocks:
        cls = " ".join(sb.get("class", []))
        no_stock = "no-stock" in cls
        sz_el = sb.select_one(".block-pattern--size-text")
        sz_jp = sz_el.text.strip() if sz_el else ""
        # mpn は backorder link or input value or sku= から取る
        mpn = None
        bo = sb.select_one("a[href*='backorder.aspx']")
        if bo:
            m = re.search(r"goods=(\d+)", bo.get("href", ""))
            if m:
                mpn = m.group(1)
        if not mpn:
            inp = sb.select_one('input[name="goods"]')
            if inp:
                mpn = inp.get("value")
        if not mpn:
            sl = sb.select_one("a[href*='sku=']")
            if sl:
                m = re.search(r"sku=(\d+)", sl.get("href", ""))
                if m:
                    mpn = m.group(1)
        all_variants.append({
            "size_jp": sz_jp,
            "size_normalized": _normalize_size(sz_jp),
            "variant_sku_mpn": mpn or "",
            "in_stock": not no_stock,
        })

    # 配置: 全 variants を color 数で等分 → 各 color に size list 割当
    sizes_per_color = []
    n_colors = len(colors)
    if n_colors == 0 or len(all_variants) == 0:
        return {"colors": colors, "sizes_per_color": [],
                "all_variants_raw": all_variants}
    per_color = len(all_variants) // n_colors if n_colors else 0
    for i, c in enumerate(colors):
        chunk = all_variants[i * per_color:(i + 1) * per_color]
        sizes_per_color.append({
            "color_jp": c["name"],
            "color_image": c["image"],
            "variants": chunk,
        })

    return {
        "colors": colors,
        "sizes_per_color": sizes_per_color,
        "all_variants_raw": all_variants,
        "parent_mpn": parent_mpn,
    }


def _fetch_via_regex(parent_mpn: str) -> Optional[dict]:
    """bs4 不在時 fallback (= 精度低、未実装、ImportError raise)."""
    raise RuntimeError("workman_scraper: bs4 必須、pip install beautifulsoup4 を実行")


def fetch_product_inventory(url: str) -> Optional[dict]:
    """Workman 商品 URL → inventory_monitor 標準 schema (= UNIQLO 等と同形式).

    AJAX で variation matrix 取得 + JSON-LD で商品名・価格取得 (= 2 fetch / 商品)。

    Returns: {
        "name": "<日本語商品名>",
        "color": "<color (= AJAX 全 color 連結 or 主 color)>",
        "product_id": "<parent_mpn>",
        "skus": [
            {"size": "<size_normalized>", "color": "<color_jp>",
             "communication_code": "<variant_sku_mpn>",
             "variant_sku_mpn": "<variant_sku_mpn>",
             "in_stock": bool, "stock_status": "InStock"/"OutOfStock",
             "stock_label": "在庫あり"/"在庫なし",
             "quantity": 1 or 0, "price_jpy": int, ...}
            for each (color × size) variant
        ],
    } or None on failure.
    """
    parent_mpn = _extract_parent_mpn(url)
    if not parent_mpn:
        return None

    # AJAX で variation 取得
    ajax = fetch_variations_via_ajax(parent_mpn)
    if not ajax or not ajax.get("sizes_per_color"):
        return None

    # JSON-LD で商品名/価格取得 (= 親 product 情報)
    raw = fetch_workman_product(url)
    name = raw.get("name", "") if raw else ""
    price = raw.get("price_jpy", 0) if raw else 0

    # 全 color の名前を joined
    colors_joined = " / ".join(c["color_jp"] for c in ajax["sizes_per_color"])

    skus = []
    for color_block in ajax["sizes_per_color"]:
        color_jp = color_block["color_jp"]
        for v in color_block["variants"]:
            sz = v.get("size_normalized") or ""
            mpn = v.get("variant_sku_mpn") or ""
            in_stock = v.get("in_stock", False)
            if not mpn:
                continue  # mpn 不在は skip (= parse 失敗)
            skus.append({
                "size": sz,
                "size_display_code": sz,
                "color": color_jp,
                "communication_code": mpn,
                "variant_sku_mpn": mpn,
                "l2Id": mpn,   # 互換: UNIQLO scraper の l2Id field 名と揃える
                "in_stock": in_stock,
                "stock_status": "InStock" if in_stock else "OutOfStock",
                "stock_label": "在庫あり" if in_stock else "在庫なし",
                "quantity": 1 if in_stock else 0,
                "price_jpy": price,
                "promo_price_jpy": price,
                "sales_active": in_stock,
            })

    return {
        "name": name,
        "color": colors_joined,
        "product_id": parent_mpn,
        "skus": skus,
        "_workman_ajax_raw": {
            "colors": ajax.get("colors"),
            "parent_mpn": parent_mpn,
            "variant_count": len(skus),
        },
    }


if __name__ == "__main__":
    import argparse
    import json
    parser = argparse.ArgumentParser(description="Workman 商品在庫取得 (Phase 2 AJAX 経路)")
    parser.add_argument("url")
    args = parser.parse_args()
    info = fetch_product_inventory(args.url)
    if not info:
        print("取得失敗")
        sys.exit(1)
    info_simple = {k: v for k, v in info.items() if k != "_workman_ajax_raw"}
    print(json.dumps(info_simple, ensure_ascii=False, indent=2))
