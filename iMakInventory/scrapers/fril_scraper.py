"""fril_scraper - Rakuten Fril (ラクマ旧サイト item.fril.jp) 在庫スクレイパー.

判定軸 (2026-04-30 検体差分で確定、TEST_LOW row 652-661 全 10 件 100% 正解):
  1. body text に「お探しのページは見つかりませんでした」 → DELETED (404 page)
  2. body text に「購入に進む」 → IN_STOCK
  3. 上記いずれにも該当せず → 判定不能 (None, fail-closed)

Mercari と異なり Fril は data-testid を使っていない (旧式 SSR HTML)。
判定は body text の固定フレーズで行う (i18n bundle 混入リスク低い、サーバー
側 render の主要本文に登場するため stable)。

検出パターンの差 (10 件検体):
  - sold/deleted (3/3): 80KB の 404 ページ、「見つかりませんでした」=1, 「購入に進む」=0
  - in_stock   (7/7): 220KB の商品詳細、「購入に進む」=1, 「見つかりませんでした」=0

返却形式 (uniqlo_scraper と契約互換):
  {"name", "product_id", "color", "status", "fetched_at", "skus": [...]}
"""
from __future__ import annotations

import re
import time
from datetime import datetime
from typing import Optional

import requests


# ============================================================================
# 設定
# ============================================================================
FRIL_ITEM_RE = re.compile(r"item\.fril\.jp/([\w-]+)")
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)
DEFAULT_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept-Language": "ja-JP,ja;q=0.9,en;q=0.5",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
TIMEOUT_SEC = 25

# 判定軸 (検体 10 件で確定、100% 正解)
DELETED_PHRASE = "お探しのページは見つかりませんでした"
IN_STOCK_PHRASE = "購入に進む"


# ============================================================================
# URL → product id
# ============================================================================
def parse_product_id(url: str) -> Optional[str]:
    if not url:
        return None
    m = FRIL_ITEM_RE.search(url)
    return m.group(1) if m else None


# ============================================================================
# HTML 文字列ベースの判定
# ============================================================================
def _detect_stock(html: str) -> tuple[Optional[bool], str]:
    """HTML から在庫状態を判定. Returns: (verdict, reason)
        verdict: True=IN_STOCK / False=SOLD/DELETED / None=判定不能 (fail-closed)
    """
    if DELETED_PHRASE in html:
        return False, "deleted_page"
    if IN_STOCK_PHRASE in html:
        return True, "buy_button"
    return None, "no_signal"


def _extract_name(html: str) -> str:
    """HTML から商品名 (<title>) を抽出。"""
    m = re.search(r"<title>(.+?)</title>", html, re.DOTALL)
    if not m:
        return ""
    title = m.group(1).strip()
    # Fril の title 形式: "出品者名 - 商品名の通販 by ..."
    # 商品名のみ抽出は厳密には不要、title 全体で OK
    return re.sub(r"\s+", " ", title)[:200]


def _extract_price_jpy(html: str) -> Optional[int]:
    """HTML から価格抽出 (商品価格 ¥xxx)."""
    m = re.search(r"￥\s*([\d,]+)|¥\s*([\d,]+)", html)
    if not m:
        return None
    raw = m.group(1) or m.group(2)
    try:
        return int(raw.replace(",", ""))
    except (ValueError, AttributeError):
        return None


# ============================================================================
# requests ベース取得
# ============================================================================
def _fetch_via_requests(url: str) -> Optional[dict]:
    """requests で Fril 商品ページを取得して在庫判定。"""
    try:
        resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=TIMEOUT_SEC)
    except requests.RequestException:
        return None

    if resp.status_code == 404:
        return {
            "name": "(deleted)",
            "in_stock": False,
            "price_jpy": None,
            "_reason": "http_404",
        }
    if resp.status_code != 200:
        return None

    html = resp.text
    in_stock, reason = _detect_stock(html)
    if in_stock is None:
        return None

    return {
        "name": _extract_name(html),
        "in_stock": in_stock,
        "price_jpy": _extract_price_jpy(html),
        "_reason": reason,
    }


# ============================================================================
# 公開 API
# ============================================================================
def fetch_product_inventory(
    url: str,
    use_selenium_fallback: bool = False,  # 現状 requests で十分、Selenium 不要
) -> Optional[dict]:
    """Fril 商品 URL から在庫情報を取得.

    Args:
        url: Fril 商品 URL (例: https://item.fril.jp/<random_id>)
        use_selenium_fallback: 現状 unused (requests path のみで動作)

    Returns:
        uniqlo_scraper と契約互換の dict、または None (取得不能・判定不能時)
    """
    pid = parse_product_id(url) or ""

    raw = _fetch_via_requests(url)
    if raw is None:
        return None

    in_stock = bool(raw.get("in_stock", False))
    status = "DELETED" if raw.get("_reason") in ("deleted_page", "http_404") else (
        "IN_STOCK" if in_stock else "SOLD_OUT"
    )

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
                "price_jpy": raw.get("price_jpy"),
            }
        ],
    }


# ============================================================================
# CLI (動作確認用)
# ============================================================================
if __name__ == "__main__":
    import sys
    test_url = sys.argv[1] if len(sys.argv) > 1 else "https://item.fril.jp/aa5c5975561c8cf81f2f2164b539de8d"
    print(f"--- Fril scrape: {test_url} ---")
    info = fetch_product_inventory(test_url)
    if info is None:
        print("  ⚠️ 判定不能 (None)")
        sys.exit(1)
    print(f"  Name:     {info['name'][:60]}")
    print(f"  Pid:      {info['product_id']}")
    print(f"  Status:   {info['status']}")
    print(f"  InStock:  {info['skus'][0]['in_stock']}")
    print(f"  Price:    ¥{info['skus'][0]['price_jpy']}")
