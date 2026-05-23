"""fril_scraper - Rakuten Fril (ラクマ旧サイト item.fril.jp) 在庫スクレイパー.

判定軸 (2026-04-30 検体差分で確定、TEST_LOW row 652-685 計 33 件で検証):
  1. class="soldout-section" 存在 → SOLD (page exists で売却済 / 商品保留)
  2. body text に「お探しのページは見つかりませんでした」 → SOLD/DELETED (404 page)
  3. body text に「購入に進む」 → IN_STOCK
  4. 上記いずれにも該当せず → 判定不能 (None, fail-closed)

Fril の SOLD には 2 ステート存在:
  - **DELETED** (出品取下げ済): 404 page に redirect、80KB
  - **SOLD-page-exists** (売却済だが page 残存): 200 OK、商品 page に
    `<section class="soldout-section">` と `<div class="photo-box__soldout_ribbon">SOLD OUT</div>`
    overlay。「購入に進む」 button 不在。

Mercari と異なり Fril は data-testid を使わない (旧式 SSR HTML)。
判定は body text の固定フレーズ + class セレクタで行う。

検体検証実績:
  - DELETED   3/3 (row 652/653/654)
  - SOLD-page-exists 1+ (row 664/673/674、検体 1 件保存)
  - IN_STOCK  7/7 (row 655-661)
  - in_stock 10件 (row 675-685) — 全件 buy_button で正解

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

# 判定軸 (検体検証で確定)
DELETED_PHRASE = "お探しのページは見つかりませんでした"
IN_STOCK_PHRASE = "購入に進む"
# SOLD-page-exists (売却済だが商品 page 残存) のシグナル
# class="soldout-section" は商品本体の wrapper、recommend widget には出ない
SOLD_SECTION_PATTERN = 'class="soldout-section"'


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

    判定優先順位:
      1. soldout-section: SOLD-page-exists 確定 (specific marker)
      2. deleted_page:    404 redirect 確定
      3. buy_button:      IN_STOCK 確定
      4. その他:          判定不能 (None)
    """
    if SOLD_SECTION_PATTERN in html:
        return False, "sold_page_exists"
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
    """HTML から価格抽出.

    2026-05-23 改修: 旧仕様は ¥XXX prefix の最初の数字を採用していたが、fril の
    現 HTML には `¥XXX` 形式 text が含まれず、JSON-LD `offers.price` のみが
    商品価格を保持している (Takaaki さん指摘 2 件、N 列が古い値で固定)。

    改修方針:
      1. JSON-LD `<script type="application/ld+json">` 内の Product.offers.price
      2. fallback: HTML 内 `"price":XXX` (= JSON-embedded)
      3. fallback: ¥XXX prefix の最初の数字 (= 旧仕様、最後の手段)
    """
    # 1. JSON-LD parse
    try:
        import json  # noqa: PLC0415
        for m_ld in re.finditer(
            r'<script[^>]*application/ld\+json[^>]*>(.+?)</script>',
            html, re.S | re.I,
        ):
            try:
                data = json.loads(m_ld.group(1))
            except Exception:
                continue
            candidates = data if isinstance(data, list) else [data]
            for c in candidates:
                if not isinstance(c, dict):
                    continue
                # @type=Product or 単体 price field
                offers = c.get("offers")
                if isinstance(offers, list):
                    offers = offers[0] if offers else None
                if isinstance(offers, dict):
                    p = offers.get("price")
                    if p is not None:
                        try:
                            return int(str(p).replace(",", ""))
                        except (ValueError, AttributeError):
                            pass
    except Exception:
        pass

    # 2. HTML 内 "price":XXX
    m_p = re.search(r'"price"\s*:\s*"?(\d+)"?', html)
    if m_p:
        try:
            return int(m_p.group(1))
        except ValueError:
            pass

    # 3. fallback: ¥XXX prefix
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
    reason = raw.get("_reason", "")
    if reason in ("deleted_page", "http_404"):
        status = "DELETED"
    elif reason == "sold_page_exists":
        status = "SOLD_OUT"
    elif in_stock:
        status = "IN_STOCK"
    else:
        status = "UNKNOWN"

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
        print("  [!] 判定不能 (None)")
        sys.exit(1)
    print(f"  Name:     {info['name'][:60]}")
    print(f"  Pid:      {info['product_id']}")
    print(f"  Status:   {info['status']}")
    print(f"  InStock:  {info['skus'][0]['in_stock']}")
    print(f"  Price:    ¥{info['skus'][0]['price_jpy']}")
