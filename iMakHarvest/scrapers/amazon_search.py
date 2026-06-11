"""amazon_search - Amazon.co.jp 検索 page から商品 URL 収集.

依頼書 sec 2 (= 2026-06-01 / 2026-06-11 一石二鳥案):
  - 入力: 検索 URL (= https://www.amazon.co.jp/s?k=G-Shock&rh=...)
  - 出力: /dp/<ASIN> URL list (= dedup 済、 順序保持)
  - **seller=Amazon.co.jp 判別は detail page 側で実施** (= 検索 page では URL のみ収集)
    検索 page UI の「Amazon 発送」 filter は ABテストで消失リスクあるため、 detail で確定が堅牢

設計原則:
  - amazon_wishlist.create_driver / chrome_profile_amazon 流用
  - pagination は &page=N で URL 化 (= 「次へ」 button click より堅牢)
  - jitter sleep 5-10s (= mercari_seller 6/3 fix と同調、 ユーザー「気を付けて」 反映)
  - HARD CAP 1000 件 / session (= 1 検索パスでの暴走防止、 完全網羅は別 path 分割)
  - captcha 検出時 即中断 + 状態返却 (caller が user 突破 + resume 判断)
"""
from __future__ import annotations

import random
import re
import time
from typing import Callable, Optional
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from selenium.webdriver.common.by import By

from scrapers.amazon_item_detail import CAPTCHA_KEYWORDS
from scrapers.amazon_wishlist import ASIN_RE, create_driver, CHROME_PROFILE_DIR

# ============================================================================
# Constants
# ============================================================================
AMAZON_SEARCH_HOST = "amazon.co.jp"
AMAZON_SEARCH_PATH = "/s"

# 1 page = 48 件 (Amazon default)、 N page 走査で N × 48 件
DEFAULT_MAX_PAGES = 25  # 25 × 48 = 1200 件相当 (= 1000 件 cap 内で十分網羅)
DEFAULT_PAGE_WAIT_SEC = 12   # 初期 hydration
DEFAULT_PAGE_INTERVAL_MIN = 5.0   # page 間隔 (= user 「気を付けて」 反映、 5-10s)
DEFAULT_PAGE_INTERVAL_MAX = 10.0
DEFAULT_HARD_CAP = 1000  # 1 session 内 暴走防止

# 検索結果 card 内 ASIN URL pattern (= /dp/<ASIN> + 派生)
# amazon_wishlist の ASIN_RE を共用

# 検索結果 card container selector (= ABテストで変動可、 fallback あり)
SEARCH_RESULT_CARD_SELECTORS = (
    "div[data-component-type='s-search-result']",
    "div.s-result-item[data-asin]",
)

# brand pre-filter: card 内 text に G-shock indicator あるか判定
# (= 6/11 ユーザー指摘「画面表示するだけで採用しないのは無駄」 対応)
GSHOCK_TITLE_PREFILTER_RE = re.compile(
    r"G[-\s]?SHOCK|Gショック|ジーショック", re.IGNORECASE,
)


# ============================================================================
# URL parser
# ============================================================================
def parse_search_url(url: str) -> Optional[dict]:
    """Amazon.co.jp/s URL から query params 抽出.

    Args:
        url: search URL (例: https://www.amazon.co.jp/s?k=G-Shock&rh=n%3A337470011)

    Returns:
        {
            "keyword": str | None,    # k= 検索キーワード
            "rh": str | None,         # rh= 絞り込み node ID (= カテゴリ等)
            "raw_url": str,
        }
        または None (= URL 形式不正)
    """
    if not url:
        return None
    try:
        p = urlparse(url)
    except Exception:
        return None
    if AMAZON_SEARCH_HOST not in (p.netloc or ""):
        return None
    if not (p.path or "").startswith(AMAZON_SEARCH_PATH):
        return None
    qs = parse_qs(p.query or "")
    keywords = qs.get("k") or []
    rh_vals = qs.get("rh") or []
    return {
        "keyword": keywords[0] if keywords else None,
        "rh": rh_vals[0] if rh_vals else None,
        "raw_url": url,
    }


def build_search_url_with_page(base_url: str, page: int) -> str:
    """検索 URL に &page=N を付与 (= 既存 page query は上書き)."""
    if page <= 1:
        return base_url
    try:
        p = urlparse(base_url)
    except Exception:
        return base_url
    qs = parse_qs(p.query or "")
    qs["page"] = [str(page)]
    new_query = urlencode({k: v[0] for k, v in qs.items() if v})
    return urlunparse((p.scheme, p.netloc, p.path, p.params, new_query, p.fragment))


def parse_asin_from_url(url: str) -> Optional[str]:
    """/dp/<ASIN> URL から ASIN を抽出 (= dedupe key)."""
    if not url:
        return None
    m = ASIN_RE.search(url)
    return m.group(1).upper() if m else None


# ============================================================================
# Listing 抽出
# ============================================================================
def _collect_asin_urls_from_search_page(
    driver, brand_prefilter: bool = True,
) -> list[str]:
    """現在 page から /dp/<ASIN> URL 一覧抽出 (= dedupe + 順序保持 + 任意 brand pre-filter).

    brand_prefilter=True (= default、 6/11 改善):
      検索結果 card text に G-shock indicator (= G-SHOCK / Gショック) ある card のみ採用、
      非 G-shock card (= CITIZEN PROMASTER 等) を URL 段で除外、
      detail fetch 件数を 30-50% 削減。
    brand_prefilter=False (= 旧挙動): 全 card から ASIN 抽出。

    card container が取れない (= ABテスト変動) 場合は fallback で 全 anchor 走査
    (= 旧挙動と同等)。
    """
    seen: set[str] = set()
    urls: list[str] = []
    cards = []
    for sel in SEARCH_RESULT_CARD_SELECTORS:
        try:
            cards = driver.find_elements(By.CSS_SELECTOR, sel)
        except Exception:
            cards = []
        if cards:
            break

    if not cards:
        # fallback: 全 anchor 走査 (= card 構造変更時の安全網)
        try:
            anchors = driver.find_elements(By.TAG_NAME, "a")
        except Exception:
            return []
        for a in anchors:
            try:
                href = a.get_attribute("href") or ""
            except Exception:
                continue
            asin = parse_asin_from_url(href)
            if not asin:
                continue
            canon = f"https://www.amazon.co.jp/dp/{asin}"
            if canon in seen:
                continue
            seen.add(canon)
            urls.append(canon)
        return urls

    # card 単位で走査 + 任意 pre-filter
    for card in cards:
        # visible check (= 6/11 ユーザー指摘: 拡張機能で hide された card は除外)
        # 「Amazon 3rd Party Seller Filter」 拡張機能は CSS display:none で第三者 card を
        # hide する。 抽出くんは画面に見えているもの だけを採用 (= 拡張機能の絞込結果を反映)。
        try:
            if not card.is_displayed():
                continue
        except Exception:
            continue
        if brand_prefilter:
            try:
                card_text = (card.text or "")[:500]
            except Exception:
                card_text = ""
            if not GSHOCK_TITLE_PREFILTER_RE.search(card_text):
                continue
        # card 内最初の ASIN-URL を採用 (= dedup 後、 順序保持)
        try:
            anchors = card.find_elements(By.TAG_NAME, "a")
        except Exception:
            anchors = []
        for a in anchors:
            try:
                href = a.get_attribute("href") or ""
            except Exception:
                continue
            asin = parse_asin_from_url(href)
            if not asin:
                continue
            canon = f"https://www.amazon.co.jp/dp/{asin}"
            if canon in seen:
                break
            seen.add(canon)
            urls.append(canon)
            break  # card 1 つにつき 1 URL
    return urls


def _detect_captcha(driver) -> bool:
    """body text から captcha 判定 (= amazon_item_detail と同 keyword)."""
    try:
        body_text = driver.find_element(By.TAG_NAME, "body").text or ""
    except Exception:
        return False
    return any(kw in body_text for kw in CAPTCHA_KEYWORDS)


# ============================================================================
# Public API
# ============================================================================
def collect_search_listing_urls(
    search_url: str,
    driver=None,
    headless: bool = False,
    max_pages: int = DEFAULT_MAX_PAGES,
    user_limit: Optional[int] = None,
    page_wait_sec: int = DEFAULT_PAGE_WAIT_SEC,
    interval_min: float = DEFAULT_PAGE_INTERVAL_MIN,
    interval_max: float = DEFAULT_PAGE_INTERVAL_MAX,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> dict:
    """Amazon.co.jp/s URL から ASIN URL 一覧取得 (= pagination で走査).

    Returns:
        {
            "search_url": str,
            "keyword": str | None,
            "rh": str | None,
            "urls": list[str],          # /dp/<ASIN> canonical
            "pages_scanned": int,
            "captcha_hit": bool,        # 途中 captcha 検出時 True で打切り
            "cap_hit": bool,
            "total_seen": int,
        }
    """
    parsed = parse_search_url(search_url)
    if parsed is None:
        raise ValueError(f"invalid Amazon search URL: {search_url}")

    effective_cap = (
        min(user_limit, DEFAULT_HARD_CAP) if user_limit and user_limit > 0
        else DEFAULT_HARD_CAP
    )

    own_driver = driver is None
    if own_driver:
        driver = create_driver(headless=headless)

    all_seen: dict[str, None] = {}  # 順序保持 dict
    captcha_hit = False
    pages_scanned = 0
    try:
        for page in range(1, max_pages + 1):
            page_url = build_search_url_with_page(search_url, page)
            try:
                driver.get(page_url)
            except Exception:
                break
            time.sleep(page_wait_sec)
            # scroll 1 回で lazy 要素 flush
            try:
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            except Exception:
                pass
            time.sleep(2)
            if _detect_captcha(driver):
                captcha_hit = True
                break
            page_urls = _collect_asin_urls_from_search_page(driver)
            new_count = 0
            for u in page_urls:
                if u not in all_seen:
                    all_seen[u] = None
                    new_count += 1
            pages_scanned = page
            if progress_callback:
                try:
                    progress_callback(
                        page,
                        len(all_seen),
                        f"page {page}: total {len(all_seen)} (+{new_count} new)",
                    )
                except Exception:
                    pass
            # cap 到達 / 新規ゼロで打切り
            if len(all_seen) >= effective_cap:
                break
            if new_count == 0:
                break
            time.sleep(random.uniform(interval_min, interval_max))

        all_urls = list(all_seen.keys())[:effective_cap]
        return {
            "search_url": search_url,
            "keyword": parsed.get("keyword"),
            "rh": parsed.get("rh"),
            "urls": all_urls,
            "pages_scanned": pages_scanned,
            "captcha_hit": captcha_hit,
            "cap_hit": len(all_seen) >= effective_cap,
            "total_seen": len(all_seen),
        }
    finally:
        if own_driver:
            try:
                driver.quit()
            except Exception:
                pass
