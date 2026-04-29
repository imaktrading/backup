"""amazon_scraper - Amazon.co.jp 商品ページの在庫スクレイパー (独立モジュール).

戦略: Plan B (Selenium scrape).
  Plan A (PA-API) はアフィリエイト売上要件があり、停止リスクがある。
  Phase 1 では Plan B (Selenium scrape) で先行実装し、運用安定後に Plan A 移行を検討。

設計原則:
  - undetected_chromedriver で Akamai 系 anti-bot 回避
  - 失敗時は None 返却 (fail-closed)
  - 在庫判定は Amazon 公式 DOM の "在庫" 表記を信頼
  - Akamai / CAPTCHA に遭遇したら例外送出 (呼出側で「自動取り下げ発動しない」)

在庫判定パターン (jp.amazon.co.jp の DOM):
  - "在庫あり" → 在庫あり
  - "残り N 点" → 在庫あり
  - "通常配送無料" → 在庫あり (補助シグナル)
  - "現在お取り扱いできません" → 在庫なし
  - "在庫切れ" → 在庫なし
  - "現在在庫切れです" → 在庫なし
  - "一時的に在庫切れ" → 在庫なし
  - 上記いずれにも該当しない → 不明 (fail-closed = None)

返却形式 (uniqlo_scraper.fetch_product_inventory と契約互換):
  {
    "name":         商品名,
    "product_id":   ASIN (例: "B0XXXXXXXX"),
    "color":        "" (バリエ未対応、Phase 2+ で拡張可),
    "fetched_at":   ISO timestamp,
    "skus": [
        {"size": "", "in_stock": bool, "quantity": 1 or 0, "price_jpy": int or None}
    ]
  }
"""
from __future__ import annotations

import json
import re
import time
import urllib.parse
from datetime import datetime
from typing import Optional


ASIN_RE = re.compile(r"/(?:dp|gp/product)/([A-Z0-9]{10})")
PRICE_RE = re.compile(r"￥\s*([\d,]+)|¥\s*([\d,]+)")

# 在庫判定軸 (2026-04-29 false-positive 12/12 バグから検体差分で確定)
# 旧コード: html 全体に「在庫切れ」キーワード grep → hidden widget で誤検出
# 新コード: cart button (id="add-to-cart-button") 存在で IN_STOCK 確定
#
# Amazon は IN_STOCK 商品の buy box にだけ <input id="add-to-cart-button">
# を render する。SOLD/取扱なし商品は <div id="outOfStock"> を出して cart
# button を出さない。これが Amazon 自身の構造的シグナルで誤検出しない。
CART_BUTTON_PATTERN = 'id="add-to-cart-button"'
OUT_OF_STOCK_DIV_PATTERN = 'id="outOfStock"'
# Amazon が「おすすめ出品の要件を満たす出品はありません」状態で render する div。
# 直販なし、3rd party seller も Featured Offer 不適格 → eBay 取り下げ判定 で SOLD 扱いが安全側。
# 2026-04-30 TEST_LOW row 116/120 で発見、検体差分で判定軸確立。
UNQUALIFIED_BUYBOX_PATTERN = 'id="unqualifiedBuyBox_feature_div"'
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


# ============================================================================
# URL → ASIN
# ============================================================================
def parse_asin(url: str) -> Optional[str]:
    """Amazon URL から ASIN を抽出."""
    if not url:
        return None
    m = ASIN_RE.search(url)
    return m.group(1) if m else None


# ============================================================================
# 在庫判定 (HTML body 解析)
# ============================================================================
def _detect_stock(html: str) -> Optional[bool]:
    """HTML から在庫状態を判定.

    判定軸 (検体差分で確定):
      1. id="add-to-cart-button" 存在 → IN_STOCK (確実、Amazon が IN_STOCK 商品にだけ render)
      2. id="outOfStock" 存在 → SOLD (Amazon が取扱なし商品に render する div)
      3. id="unqualifiedBuyBox_feature_div" 存在 → SOLD (おすすめ出品なし状態、
         直販なし + 3rd party Featured Offer 不適格 = 実質購入不可)
      4. どれも無し → 判定不能 (fail-closed = None、誤取下げ防止)

    Note: HTML 全体に「在庫切れ」「現在お取り扱いできません」キーワードが
    hidden widget (related items / variation placeholder 等) に含まれる
    ため、旧コードの grep ベース判定は false positive 多発 (12/12 検証で発覚)。

    Returns:
        True  : 在庫あり
        False : 在庫切れ / 取扱なし / おすすめ出品なし
        None  : 判定不能 (新パターン or anti-bot)
    """
    # IN_STOCK 直接シグナル (最優先、構造的に確実)
    if CART_BUTTON_PATTERN in html:
        return True
    # SOLD 直接シグナル (2 種類)
    if OUT_OF_STOCK_DIV_PATTERN in html:
        return False
    if UNQUALIFIED_BUYBOX_PATTERN in html:
        return False
    # 既知パターンに合致せず → 判定不能
    return None


def _extract_name(html: str) -> str:
    """HTML から商品名を抽出 (productTitle div の text)."""
    m = re.search(
        r'<span\s+id="productTitle"[^>]*>\s*(.+?)\s*</span>',
        html,
        re.DOTALL,
    )
    if m:
        return re.sub(r"\s+", " ", m.group(1)).strip()
    # fallback: <title> tag
    m = re.search(r"<title>(.+?)</title>", html, re.DOTALL)
    return m.group(1).strip() if m else ""


def _extract_price_jpy(html: str) -> Optional[int]:
    """HTML から価格 (¥) を抽出。複数候補のうち最初の数値を返す."""
    m = PRICE_RE.search(html)
    if not m:
        return None
    raw = m.group(1) or m.group(2)
    try:
        return int(raw.replace(",", ""))
    except (ValueError, AttributeError):
        return None


# ============================================================================
# 一次方式: requests (高速・低負荷)
# ============================================================================
def _fetch_via_requests(url: str) -> Optional[dict]:
    """requests で Amazon 商品ページを取得。

    Returns: 抽出済 dict / None (HTTP 失敗時 or 在庫判定不能時)
    """
    try:
        import requests  # noqa: PLC0415
    except ImportError:
        return None

    try:
        resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=TIMEOUT_SEC)
    except requests.RequestException:
        return None

    if resp.status_code == 404:
        return {"name": "(deleted)", "in_stock": False, "price_jpy": None}
    if resp.status_code != 200:
        return None

    html = resp.text
    # Amazon は bot 検知時に CAPTCHA ページを返す → "Type the characters" で判定
    if "Type the characters" in html or "captcha" in html.lower()[:5000]:
        return None  # bot 検知 → fallback to Selenium

    in_stock = _detect_stock(html)
    if in_stock is None:
        return None  # 判定不能 → fallback to Selenium

    return {
        "name": _extract_name(html),
        "in_stock": in_stock,
        "price_jpy": _extract_price_jpy(html),
    }


# ============================================================================
# 二次方式: Selenium fallback
# ============================================================================
def _fetch_via_selenium(url: str, headless: bool = False) -> Optional[dict]:
    """Selenium (undetected_chromedriver) で取得 (anti-bot 強化時用)."""
    try:
        import undetected_chromedriver as uc  # noqa: PLC0415
    except ImportError:
        raise RuntimeError(
            "undetected_chromedriver 未インストール。"
            "pip install undetected-chromedriver で導入してください。"
        )

    options = uc.ChromeOptions()
    options.add_argument("--no-sandbox")
    options.add_argument("--lang=ja-JP")
    if headless:
        options.add_argument("--headless=new")

    driver = uc.Chrome(options=options, version_main=146)
    try:
        driver.get(url)
        time.sleep(5)
        html = driver.page_source
    finally:
        driver.quit()

    in_stock = _detect_stock(html)
    if in_stock is None:
        return None
    return {
        "name": _extract_name(html),
        "in_stock": in_stock,
        "price_jpy": _extract_price_jpy(html),
    }


# ============================================================================
# 公開 API
# ============================================================================
def fetch_product_inventory(
    url: str,
    use_selenium_fallback: bool = True,
) -> Optional[dict]:
    """Amazon.co.jp 商品 URL から在庫・価格情報を取得.

    Args:
        url: Amazon 商品 URL (例: https://www.amazon.co.jp/dp/B0XXXXXXXX)
        use_selenium_fallback: requests 失敗時に Selenium fallback を使うか

    Returns:
        uniqlo_scraper と契約互換の dict、または None (取得不能・判定不能時)。
        fail-closed 原則により、None の場合は呼出元で「自動取り下げ発動しない」。
    """
    asin = parse_asin(url) or ""

    raw = _fetch_via_requests(url)
    if raw is None and use_selenium_fallback:
        raw = _fetch_via_selenium(url)
    if raw is None:
        return None

    return {
        "name": raw.get("name", ""),
        "product_id": asin,
        "color": "",
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
        "skus": [
            {
                "size": "",
                "in_stock": bool(raw.get("in_stock", False)),
                "quantity": 1 if raw.get("in_stock") else 0,
                "price_jpy": raw.get("price_jpy"),
            }
        ],
    }


# ============================================================================
# CLI (動作確認用)
# ============================================================================
if __name__ == "__main__":
    import sys
    test_url = (
        sys.argv[1]
        if len(sys.argv) > 1
        else "https://www.amazon.co.jp/dp/B0XXXXXXXX"  # ダミー、要差替
    )
    print(f"--- Amazon scrape: {test_url} ---")
    info = fetch_product_inventory(test_url, use_selenium_fallback=False)
    if info is None:
        print("  ⚠️ 取得不能 (None) — Selenium fallback を試すか URL を確認してください")
        sys.exit(1)
    print(f"  Name:    {info['name'][:60]}")
    print(f"  ASIN:    {info['product_id']}")
    print(f"  InStock: {info['skus'][0]['in_stock']}")
    print(f"  Price:   ¥{info['skus'][0]['price_jpy']}")
