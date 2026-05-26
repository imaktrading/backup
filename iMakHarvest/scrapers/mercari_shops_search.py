"""mercari_shops_search - メルカリショップ 検索 (= mercari-shops.com/search) 抽出.

mercari_seller の Shop 検索 版。 入口 URL は:
  https://mercari-shops.com/search?shop_ids=<id>&keyword=<kw>&in_stock=true&...

特徴 (= 5/26 POC で確認):
  - listing card: <a href='https://jp.mercari.com/shops/product/<UUID>?source=shops_search'>
  - lazy load: **scroll のみ** (= 「もっと見る」 button 無し、 フリマアシスト 拡張機能 不要)
  - 在庫絞り: in_stock=true query で絞り済 → 詳細 SOLD 判定 簡略化 OK
  - 詳細 URL は jp.mercari.com domain (= 同 domain)
  - 詳細取得は scrapers.mercari_shops_item_detail.fetch_detail を流用

設計原則:
  - mercari_seller の anonymous chrome profile / _drain_alerts / rate limit を流用
  - フリマアシスト install 不要 (= scroll で全件取れる、 拡張機能 干渉なし)
  - dedupe key: shop product UUID
  - HARD CAP: 1000 件 (= scroll で取れる ネイティブ上限 ~800 件 + 安全マージン)
  - card_id group 化 / Vision 統合は **しない** (= 想定商材は TCG 以外、 fetch_detail 側で
    color/size は自動 skip 判定。 同 listing 集約は今フェーズ scope 外)
"""
from __future__ import annotations

import os
import random
import re
import time
from typing import Callable, Optional
from urllib.parse import parse_qs, urlparse

from selenium.webdriver.common.by import By

from scrapers import mercari_shops_item_detail
from scrapers.mercari_seller import (
    CHROME_PROFILE_DIR_ANON,
    _drain_alerts,
    create_anonymous_driver,
)

# ============================================================================
# Constants
# ============================================================================
# mercari-shops.com search URL pattern
SHOPS_SEARCH_HOST = "mercari-shops.com"
SHOPS_SEARCH_PATH = "/search"

# listing card URL pattern: /shops/product/<UUID> (UUID = 英数字 22 文字程度)
# regex 抽出 + dedupe key として使用
SHOPS_PRODUCT_PATH_RE = re.compile(r"/shops/product/([A-Za-z0-9]+)")

# scroll パラメータ (= 5/26 POC: 759 件 / 8 回 scroll で 増加止まる、 余裕 もって 30 回上限)
DEFAULT_MAX_SCROLLS = 30
DEFAULT_SCROLL_INTERVAL_SEC = 2.0
DEFAULT_NO_PROGRESS_THRESHOLD = 3  # 連続変化なし回数で stop
DEFAULT_INITIAL_WAIT_SEC = 15  # 初期 hydration

# HARD CAP (= POC 実機で 759 件取れた、 1000 件で安全マージン)
HARD_CAP_PER_SESSION = 1000
DEFAULT_USER_LIMIT = 0  # = 上限なし (= HARD_CAP まで)

# rate limit (= 詳細取得時、 mercari_seller と同値)
DEFAULT_DETAIL_RATE_LIMIT_MIN_SEC = 2.0
DEFAULT_DETAIL_RATE_LIMIT_MAX_SEC = 4.0


# ============================================================================
# URL parser
# ============================================================================
def parse_search_url(url: str) -> Optional[dict]:
    """mercari-shops.com/search URL から query params 抽出.

    Args:
        url: search URL (例: https://mercari-shops.com/search?shop_ids=X&keyword=Y&...)

    Returns:
        {
            "shop_id": str | None,    # 主要 shop_id (= shop_ids 1 件目)
            "keyword": str | None,    # 検索 keyword (= URL decoded)
            "in_stock": bool,         # 在庫絞込 (= default True)
            "raw_url": str,           # 受領 URL そのまま
        }
        または None (= URL 形式不正)
    """
    if not url:
        return None
    try:
        p = urlparse(url)
    except Exception:
        return None
    if SHOPS_SEARCH_HOST not in (p.netloc or ""):
        return None
    qs = parse_qs(p.query or "")
    shop_ids = qs.get("shop_ids") or []
    keywords = qs.get("keyword") or []
    in_stock_vals = qs.get("in_stock") or []
    in_stock = (in_stock_vals[0].lower() == "true") if in_stock_vals else True
    return {
        "shop_id": shop_ids[0] if shop_ids else None,
        "keyword": keywords[0] if keywords else None,
        "in_stock": in_stock,
        "raw_url": url,
    }


def parse_product_id(url: str) -> Optional[str]:
    """/shops/product/<UUID> URL から product_id を抽出 (= dedupe key)."""
    if not url:
        return None
    m = SHOPS_PRODUCT_PATH_RE.search(url)
    if m:
        return m.group(1)
    return None


# ============================================================================
# Listing 抽出
# ============================================================================
def _collect_product_urls_from_page(driver) -> list[str]:
    """現在 page から /shops/product/<UUID> URL 一覧抽出 (= dedupe + 順序保持).

    UnexpectedAlertPresentException 対策で 1 回 retry 込み (= seller 版と同パターン)。
    """
    try:
        anchors = driver.find_elements(By.TAG_NAME, "a")
    except Exception:
        _drain_alerts(driver)
        try:
            anchors = driver.find_elements(By.TAG_NAME, "a")
        except Exception:
            return []
    seen: set[str] = set()
    urls: list[str] = []
    for a in anchors:
        try:
            href = a.get_attribute("href") or ""
        except Exception:
            continue
        product_id = parse_product_id(href)
        if not product_id:
            continue
        # 正規化 (= ?source=shops_search クエリは除いて canonical URL に)
        canon = f"https://jp.mercari.com/shops/product/{product_id}"
        if canon in seen:
            continue
        seen.add(canon)
        urls.append(canon)
    return urls


def _scroll_until_done(
    driver,
    target_count: int,
    max_scrolls: int = DEFAULT_MAX_SCROLLS,
    interval: float = DEFAULT_SCROLL_INTERVAL_SEC,
    no_progress_threshold: int = DEFAULT_NO_PROGRESS_THRESHOLD,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> int:
    """target 件まで or 連続変化なしで 自動 stop するまで scroll を続ける.

    Returns: 最終取得件数
    """
    last_count = len(_collect_product_urls_from_page(driver))
    no_progress = 0
    for i in range(max_scrolls):
        if last_count >= target_count:
            return last_count
        try:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        except Exception:
            pass
        time.sleep(interval)
        _drain_alerts(driver)
        current = len(_collect_product_urls_from_page(driver))
        if progress_callback:
            try:
                progress_callback(i + 1, current, f"scroll #{i+1}: {current} 件")
            except Exception:
                pass
        if current == last_count:
            no_progress += 1
            if no_progress >= no_progress_threshold:
                break
        else:
            no_progress = 0
        last_count = current
    return last_count


def resolve_effective_cap(user_limit: Optional[int]) -> int:
    if user_limit is None or not isinstance(user_limit, int) or user_limit <= 0:
        return HARD_CAP_PER_SESSION
    return min(user_limit, HARD_CAP_PER_SESSION)


# ============================================================================
# Public API
# ============================================================================
def collect_shops_search_listing_urls(
    search_url: str,
    driver=None,
    headless: bool = False,
    user_limit: Optional[int] = DEFAULT_USER_LIMIT,
    max_scrolls: int = DEFAULT_MAX_SCROLLS,
    initial_wait_sec: int = DEFAULT_INITIAL_WAIT_SEC,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> dict:
    """mercari-shops.com search URL から listing 一覧取得.

    Returns:
        {
            "search_url": str,
            "shop_id": str | None,
            "keyword": str | None,
            "urls": list[str],
            "effective_cap": int,
            "cap_hit": bool,
            "total_seen": int,
        }
    """
    parsed = parse_search_url(search_url)
    if parsed is None:
        raise ValueError(f"invalid mercari-shops search URL: {search_url}")

    effective_cap = resolve_effective_cap(user_limit)

    own_driver = driver is None
    if own_driver:
        driver = create_anonymous_driver(headless=headless)
    try:
        driver.get(search_url)
        try:
            driver.maximize_window()
        except Exception:
            pass
        try:
            driver.execute_script("window.focus();")
        except Exception:
            pass
        time.sleep(initial_wait_sec)
        total_seen = _scroll_until_done(
            driver,
            target_count=effective_cap + 1,
            max_scrolls=max_scrolls,
            progress_callback=progress_callback,
        )
        _drain_alerts(driver)
        all_urls = _collect_product_urls_from_page(driver)
        cap_hit = total_seen > effective_cap
        return {
            "search_url": search_url,
            "shop_id": parsed.get("shop_id"),
            "keyword": parsed.get("keyword"),
            "urls": all_urls[:effective_cap],
            "effective_cap": effective_cap,
            "cap_hit": cap_hit,
            "total_seen": total_seen,
        }
    finally:
        if own_driver:
            try:
                driver.quit()
            except Exception:
                pass


def collect_shops_search_with_details(
    search_url: str,
    driver=None,
    headless: bool = False,
    user_limit: Optional[int] = DEFAULT_USER_LIMIT,
    max_scrolls: int = DEFAULT_MAX_SCROLLS,
    initial_wait_sec: int = DEFAULT_INITIAL_WAIT_SEC,
    exclude_sold: bool = False,  # in_stock=true で絞り済の前提なので default False
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    listing_progress_callback: Optional[Callable[[int, int, str], None]] = None,
    rate_limit_min_sec: float = DEFAULT_DETAIL_RATE_LIMIT_MIN_SEC,
    rate_limit_max_sec: float = DEFAULT_DETAIL_RATE_LIMIT_MAX_SEC,
) -> dict:
    """listing URL 取得 + 各 URL の詳細取得.

    Returns:
        {
            "search_url": str,
            "shop_id": str | None,
            "keyword": str | None,
            "items": list[dict],          # 詳細 dict (= mercari_likes 同 schema)
            "effective_cap": int,
            "cap_hit": bool,
            "total_seen": int,
            "skipped_sold": int,
            "skipped_detail_failed": int,
        }
    """
    own_driver = driver is None
    if own_driver:
        driver = create_anonymous_driver(headless=headless)
    try:
        url_result = collect_shops_search_listing_urls(
            search_url=search_url,
            driver=driver,
            headless=headless,
            user_limit=user_limit,
            max_scrolls=max_scrolls,
            initial_wait_sec=initial_wait_sec,
            progress_callback=listing_progress_callback,
        )
        urls = url_result["urls"]
        _drain_alerts(driver)
        items: list[dict] = []
        skipped_sold = 0
        skipped_detail_failed = 0
        total = len(urls)
        for i, url in enumerate(urls, start=1):
            if progress_callback:
                try:
                    progress_callback(i, total, url)
                except Exception:
                    pass
            detail = mercari_shops_item_detail.fetch_detail(driver, url)
            if detail is None:
                merged = {
                    "url": url,
                    "item_id": parse_product_id(url),
                    "title": "",
                    "price_jpy": None,
                    "condition": "",
                    "description": "",
                    "image_urls": [],
                    "in_stock": None,
                    "status": "UNKNOWN",
                    "size": "",
                    "color": "",
                }
                skipped_detail_failed += 1
            else:
                merged = {"url": url, "item_id": parse_product_id(url), **detail}

            if exclude_sold and merged.get("in_stock") is False:
                skipped_sold += 1
                if i < total and rate_limit_max_sec > 0:
                    time.sleep(random.uniform(rate_limit_min_sec, rate_limit_max_sec))
                continue
            items.append(merged)

            # rate limit (= 連続詳細取得 アクセス回避)
            if i < total and rate_limit_max_sec > 0:
                time.sleep(random.uniform(rate_limit_min_sec, rate_limit_max_sec))

        return {
            "search_url": url_result["search_url"],
            "shop_id": url_result["shop_id"],
            "keyword": url_result["keyword"],
            "items": items,
            "effective_cap": url_result["effective_cap"],
            "cap_hit": url_result["cap_hit"],
            "total_seen": url_result["total_seen"],
            "skipped_sold": skipped_sold,
            "skipped_detail_failed": skipped_detail_failed,
        }
    finally:
        if own_driver:
            try:
                driver.quit()
            except Exception:
                pass
