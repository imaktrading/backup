"""snkrdunk_scraper - スニダン (SNKRDUNK) PSA10 中古 商品在庫 scraper.

5/17 commit (Phase 1): iMakTCG 補仕入元拡充の一環、PSA10 TCG 在庫監視。
HTTP-only (Selenium 不要)、JSON-LD parse で完結。

対象 URL 形式:
  https://snkrdunk.com/apparels/{model_id}/used/{instance_id}
  (= PSA10 鑑定済 1 個体 出品 page)

判定 logic:
  - HTTP 200 + JSON-LD `availability:"https://schema.org/InStock"` → 在庫あり (qty=1)
  - HTTP 404 → 削除/売切 (= 廃番、status=DELETED)
  - HTTP 200 + availability!=InStock → 売切中 (= status=SOLD_OUT)
  - その他 → 不確定 (= status=UNKNOWN、fail-closed で in_stock=False)

仕入元特性:
  - 1 URL = 1 個体 (variation なし、size/color 無関係)
  - 売れた瞬間に 404 → AC-AG 中の他 URL で listing 維持 (= 既存 ichibankuji pattern)
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from typing import Optional

import requests

_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/136.0.0.0 Safari/537.36"),
    "Accept-Language": "ja-JP,ja;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
_TIMEOUT_SEC = 15

_PRODUCT_URL_RE = re.compile(r"snkrdunk\.com/apparels/(\d+)/used/(\d+)")


def parse_product_id(url: str) -> Optional[str]:
    """URL から (model_id, instance_id) 抽出 → "model:instance" 形式 product_id 返却.

    例: https://snkrdunk.com/apparels/159278/used/45538280 → "159278:45538280"
    """
    if not url:
        return None
    m = _PRODUCT_URL_RE.search(url)
    if not m:
        return None
    return f"{m.group(1)}:{m.group(2)}"


def _extract_jsonld_product(html: str) -> Optional[dict]:
    """HTML 内の application/ld+json から @type=Product を抽出."""
    for m in re.finditer(
        r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.+?)</script>',
        html, re.S | re.I,
    ):
        try:
            data = json.loads(m.group(1))
        except Exception:
            continue
        # 単一 dict or list の可能性
        candidates = data if isinstance(data, list) else [data]
        for c in candidates:
            if isinstance(c, dict) and c.get("@type") == "Product":
                return c
            # @graph 内 product
            if isinstance(c, dict) and "@graph" in c:
                for g in c.get("@graph", []):
                    if isinstance(g, dict) and g.get("@type") == "Product":
                        return g
    return None


def _fetch_via_requests(url: str) -> dict:
    """requests で fetch、status + 在庫情報 dict を返却."""
    out = {"http_status": None, "in_stock": False, "name": "", "price_jpy": None,
           "_reason": "unknown"}
    try:
        r = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT_SEC, allow_redirects=True)
    except Exception as e:
        out["_reason"] = f"http_error:{type(e).__name__}"
        return out

    out["http_status"] = r.status_code
    if r.status_code == 404:
        out["_reason"] = "http_404"
        return out
    if r.status_code != 200:
        out["_reason"] = f"http_{r.status_code}"
        return out

    product = _extract_jsonld_product(r.text)
    if not product:
        out["_reason"] = "jsonld_missing"
        return out

    out["name"] = product.get("name", "")
    offers = product.get("offers") or {}
    if isinstance(offers, list):
        offers = offers[0] if offers else {}
    out["price_jpy"] = offers.get("price") if offers else None
    availability = (offers.get("availability") or "") if isinstance(offers, dict) else ""

    # 2026-05-25 SOLD 判定 強化:
    # JSON-LD `availability` は SNKRDUNK 側で売却後も `InStock` 維持されるバグあり
    # (= 358589046154 ケース、 5/24 売却済でも JSON-LD InStock 返却)。
    # HTML 内 `<div id="app" class="content used-item-detail sold">` が実 SOLD signal。
    # JSON-LD InStock + HTML class `sold` あれば SOLD_OUT 優先 (= HTML 真値)。
    html_sold = bool(re.search(
        r'<div\s+id=["\']app["\'][^>]*class=["\'][^"\']*\bsold\b[^"\']*["\']',
        r.text, re.I,
    ))
    if html_sold:
        out["in_stock"] = False
        out["_reason"] = "html_class_sold"
    elif "InStock" in availability:
        out["in_stock"] = True
        out["_reason"] = "instock"
    else:
        out["_reason"] = f"availability:{availability.split('/')[-1] if availability else 'unknown'}"
    return out


def fetch_product_inventory(
    url: str,
    use_selenium_fallback: bool = False,   # 互換: 未使用 (snkrdunk は HTTP-only)
) -> Optional[dict]:
    """スニダン 商品 URL → uniqlo/fril scraper と契約互換の dict.

    Returns: {
        "name": str, "product_id": "<model>:<instance>", "color": "",
        "status": "IN_STOCK"/"SOLD_OUT"/"DELETED"/"UNKNOWN",
        "fetched_at": iso8601,
        "skus": [{"size": "", "in_stock": bool, "quantity": 0 or 1, "price_jpy": int or None}]
    } or None on fetch failure.
    """
    pid = parse_product_id(url) or ""
    raw = _fetch_via_requests(url)
    if raw["http_status"] is None:
        return None  # 通信失敗

    reason = raw.get("_reason", "")
    in_stock = bool(raw.get("in_stock", False))

    if reason == "http_404":
        status = "DELETED"
    elif in_stock:
        status = "IN_STOCK"
    elif reason == "html_class_sold" or reason.startswith("availability:"):
        # 2026-05-25: HTML class `sold` 検出 も SOLD_OUT に分類
        # (= JSON-LD InStock + HTML sold の場合、 HTML 真値を採用)
        status = "SOLD_OUT"
    else:
        status = "UNKNOWN"

    try:
        price = int(raw.get("price_jpy")) if raw.get("price_jpy") is not None else None
    except (TypeError, ValueError):
        price = None

    return {
        "name": raw.get("name", ""),
        "product_id": pid,
        "color": "",
        "status": status,
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
        "skus": [
            {
                "size": "",
                "in_stock": in_stock,
                "quantity": 1 if in_stock else 0,
                "price_jpy": price,
            }
        ],
    }


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    test_url = sys.argv[1] if len(sys.argv) > 1 else \
        "https://snkrdunk.com/apparels/159278/used/45538280"
    print(f"--- snkrdunk scrape: {test_url} ---")
    info = fetch_product_inventory(test_url)
    if info is None:
        print("  [!] 通信失敗 (None)")
        sys.exit(1)
    print(f"  Name:     {info['name'][:60]}")
    print(f"  Pid:      {info['product_id']}")
    print(f"  Status:   {info['status']}")
    print(f"  InStock:  {info['skus'][0]['in_stock']}")
    print(f"  Price:    ¥{info['skus'][0]['price_jpy']}")
