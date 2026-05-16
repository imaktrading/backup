"""workman_official - ワークマン公式オンラインストアから商品データを取得.

設計原則:
  - HTTP-only (requests + BeautifulSoup)、Selenium 不要
  - Schema.org JSON-LD (`application/ld+json`) を主軸に商品データ抽出
  - color はカタカナで JSON-LD に直記述されるため Vision AI 不要
  - 失敗時は raise (caller が retry/log を判断)
  - 既存 Mercari/Amazon/Shops コードは一切 import せず独立

URL 構造:
  - 商品ページ: https://workman.jp/shop/g/g<13桁mpn>/
    例: https://workman.jp/shop/g/g2300011882014/
  - ASP.NET (.aspx) 製、初期 HTML に商品データ埋込済 (CSR ではない)

返却形式:
    {
        "url": "https://workman.jp/shop/g/g<mpn>/",
        "mpn": "2300011882014",
        "title": "ゼロステージアイストライブレギンス",
        "price_jpy": 2500,
        "color": "ブラック",
        "image_urls": ["https://workman.jp/img/goods/S/11882_t1.jpg"],
        "in_stock": True,
        "status": "ON_SALE",
        "size": "",  # JSON-LD に無いため空文字 (Workman は 1 URL = 1 SKU 構造)
        "brand": "その他ブランド",
        "release_date": "2026/03/04",
    }
"""
from __future__ import annotations

import json
import re
import time
from typing import Optional

import requests


# 商品 URL → mpn (13 桁)
WORKMAN_PRODUCT_URL_RE = re.compile(r"workman\.jp/shop/g/g(\d{13})", re.IGNORECASE)
# mpn 単独 (13 桁、`workman:` prefix 後の dedupe key 用)
WORKMAN_MPN_RE = re.compile(r"^\d{13}$")

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja-JP,ja;q=0.9,en;q=0.8",
}
TIMEOUT_SEC = 15
DEFAULT_RATE_LIMIT_SEC = 1.0  # 連続 fetch 時の sleep (workman 公式へ礼儀)


def parse_workman_mpn(url: str) -> Optional[str]:
    """Workman 商品 URL から mpn (13 桁) を抽出. 一致しなければ None."""
    if not url:
        return None
    m = WORKMAN_PRODUCT_URL_RE.search(url)
    return m.group(1) if m else None


def normalize_workman_url(url_or_mpn: str) -> str:
    """URL or mpn → 正規化された商品 URL (`https://workman.jp/shop/g/g<mpn>/`)."""
    if not url_or_mpn:
        raise ValueError("URL/mpn が空です")
    s = url_or_mpn.strip()
    # mpn 直渡し
    if WORKMAN_MPN_RE.match(s):
        return f"https://workman.jp/shop/g/g{s}/"
    # URL から mpn 抽出
    mpn = parse_workman_mpn(s)
    if not mpn:
        raise ValueError(f"Workman 商品 URL の形式が不正: {url_or_mpn}")
    return f"https://workman.jp/shop/g/g{mpn}/"


def extract_jsonld_product(html: str) -> Optional[dict]:
    """HTML 内から Schema.org JSON-LD の Product schema を 1 つ抽出.

    見つからない or parse 失敗 → None。
    """
    if not html:
        return None
    for m in re.finditer(
        r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>',
        html,
        re.DOTALL,
    ):
        block = m.group(1).strip()
        if not block:
            continue
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        # 配列の場合は Product を探す
        if isinstance(data, list):
            for d in data:
                if isinstance(d, dict) and d.get("@type") == "Product":
                    return d
        elif isinstance(data, dict) and data.get("@type") == "Product":
            return data
    return None


def _resolve_image_high_res(thumb_url: str) -> str:
    """thumb URL (`_t1.jpg`) を高解像度 (`_l1.jpg`) に変換. 一致しなければそのまま."""
    if not thumb_url:
        return ""
    # `/img/goods/S/11882_t1.jpg` → `/img/goods/L/11882_l1.jpg` パターン (推測、要検証)
    # 安全策として t1 → l1 のみ置換、ディレクトリ S → L は変更しない (404 リスク)
    return re.sub(r"_t(\d+)\.(jpg|jpeg|png|webp)$", r"_l\1.\2", thumb_url, flags=re.IGNORECASE)


def _availability_to_status(avail: str) -> tuple[bool, str]:
    """Schema.org availability → (in_stock, status string)."""
    if not avail:
        return None, "UNKNOWN"
    low = avail.lower()
    if "outofstock" in low or "out_of_stock" in low or "discontinued" in low:
        return False, "OUT_OF_STOCK"
    if "instock" in low or "in_stock" in low or "preorder" in low:
        return True, "ON_SALE"
    return None, "UNKNOWN"


def parse_workman_product_html(html: str, url: str = "") -> Optional[dict]:
    """商品ページ HTML から商品データを抽出して dict 返却.

    JSON-LD Product schema が主軸。見つからない場合 None。
    """
    jsonld = extract_jsonld_product(html)
    if not jsonld:
        return None

    name = (jsonld.get("name") or "").strip()
    color = (jsonld.get("color") or "").strip()
    mpn = (jsonld.get("mpn") or "").strip()
    description = (jsonld.get("description") or "").strip()
    release_date = (jsonld.get("releaseDate") or "").strip()

    # brand は dict or str
    brand_raw = jsonld.get("brand") or ""
    if isinstance(brand_raw, dict):
        brand = (brand_raw.get("name") or "").strip()
    else:
        brand = str(brand_raw).strip()

    image_thumb = (jsonld.get("image") or "").strip()
    # 高解像度版もリストに含める (低解像度のみが取れた時の保険)
    image_urls = []
    if image_thumb:
        image_urls.append(image_thumb)
        hi = _resolve_image_high_res(image_thumb)
        if hi and hi != image_thumb:
            image_urls.append(hi)

    offers = jsonld.get("offers") or {}
    price = offers.get("price")
    try:
        price_jpy = int(price) if price is not None else None
    except (ValueError, TypeError):
        price_jpy = None
    availability = offers.get("availability") or ""
    in_stock, status = _availability_to_status(availability)

    # URL 推定 (引数優先、無ければ JSON-LD isSimilarTo / mpn から構築)
    final_url = url.strip() if url else ""
    if not final_url:
        similar = jsonld.get("isSimilarTo") or {}
        if isinstance(similar, dict):
            final_url = (similar.get("url") or "").strip()
    if not final_url and mpn:
        final_url = f"https://workman.jp/shop/g/g{mpn}/"

    return {
        "url": final_url,
        "mpn": mpn,
        "title": name,
        "price_jpy": price_jpy,
        "color": color,
        "image_urls": image_urls,
        "in_stock": in_stock,
        "status": status,
        "size": "",  # Workman は 1 URL = 1 SKU 構造、サイズは別 mpn で展開される
        "brand": brand,
        "release_date": release_date,
        "condition": "New",  # workman 公式は全て新品
        "description": description,
    }


def fetch_product(
    url: str,
    timeout: float = TIMEOUT_SEC,
    session: Optional[requests.Session] = None,
) -> Optional[dict]:
    """Workman 商品 URL から商品データを取得.

    Returns:
        商品データ dict (parse_workman_product_html 参照) または None (取得失敗 / JSON-LD 不在)。

    例外:
        ValueError: URL 形式が不正
        requests.HTTPError: HTTP エラー (404 等は raise、caller hand handling)
    """
    target_url = normalize_workman_url(url)
    sess = session or requests
    resp = sess.get(target_url, headers=DEFAULT_HEADERS, timeout=timeout)
    resp.raise_for_status()
    return parse_workman_product_html(resp.text, url=target_url)


def fetch_products(
    urls: list[str],
    rate_limit_sec: float = DEFAULT_RATE_LIMIT_SEC,
    progress_callback=None,
) -> list[dict]:
    """複数 URL を順次 fetch (rate limited).

    Args:
        urls: Workman 商品 URL list
        rate_limit_sec: 各 fetch 間の sleep (workman 公式への礼儀)
        progress_callback: callable(current, total, message) | None

    Returns:
        成功した商品データのみ list (失敗は warning log のみで結果から除外)
    """
    sess = requests.Session()
    results: list[dict] = []
    total = len(urls)
    for i, url in enumerate(urls, start=1):
        if progress_callback:
            try:
                progress_callback(i, total, url)
            except Exception:
                pass
        try:
            data = fetch_product(url, session=sess)
        except (requests.RequestException, ValueError) as e:
            print(f"  ⚠️ [workman] fetch 失敗 ({type(e).__name__}): {url}")
            data = None
        if data:
            results.append(data)
        else:
            print(f"  ⚠️ [workman] JSON-LD parse 失敗 or 商品不在: {url}")
        if rate_limit_sec > 0 and i < total:
            time.sleep(rate_limit_sec)
    return results


# ============================================================================
# CLI (動作確認用)
# ============================================================================
if __name__ == "__main__":
    import argparse
    import sys

    ap = argparse.ArgumentParser()
    ap.add_argument(
        "url",
        nargs="?",
        default="https://workman.jp/shop/g/g2300011882014/",
        help="Workman 商品 URL (デフォルト: ゼロステージレギンス)",
    )
    args = ap.parse_args()

    print(f"--- fetch: {args.url}")
    info = fetch_product(args.url)
    if info is None:
        print("  ❌ 取得失敗")
        sys.exit(1)
    info_disp = dict(info)
    info_disp["description"] = (info_disp["description"] or "")[:120]
    print(json.dumps(info_disp, ensure_ascii=False, indent=2))
