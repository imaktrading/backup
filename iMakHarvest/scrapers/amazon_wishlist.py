"""amazon_wishlist - Amazon 公開ウィッシュリストから商品 URL を収集 (Selenium ベース).

Mercari (`mercari_likes.py`) の Amazon 版。Mercari コードは一切 import せず独立。

設計原則:
  - 公開ウィッシュリスト URL を入力 (`/hz/wishlist/ls/<LIST_ID>` を含む URL)
  - 公開済リストならログイン不要
  - undetected_chromedriver は Mercari と別 profile (`chrome_profile_amazon`)
  - 失敗時は raise (caller が retry/log を判断)
  - 推測・フォールバック禁止 (CLAUDE.md fail-closed)。ASIN 抽出不能 → 該当アイテムは除外

返却形式:
    [
      {"url": "https://www.amazon.co.jp/dp/B08N5WRWNW", "asin": "B08N5WRWNW"},
      ...
    ]
"""
from __future__ import annotations

import os
import re
import time
from typing import Optional

CHROME_PROFILE_DIR = r"C:\Users\imax2\local_data\iMakHarvest\chrome_profile_amazon"
CHROME_VERSION_MAIN = 148  # Chrome 自動更新追従 (2026-05-09: 146 → 148)

# 公開ウィッシュリスト URL: https://www.amazon.co.jp/hz/wishlist/ls/<LIST_ID>(?ref=...)
WISHLIST_URL_RE = re.compile(r"/hz/wishlist/ls/([A-Z0-9]+)", re.IGNORECASE)

# 商品 URL → ASIN (10 桁英数字).
# /dp/<ASIN>, /gp/product/<ASIN>, /gp/aw/d/<ASIN> をカバー
ASIN_RE = re.compile(
    r"/(?:dp|gp/product|gp/aw/d)/([A-Z0-9]{10})(?:[/?]|$)",
    re.IGNORECASE,
)

# Wishlist DOM:
#   <ul id="g-items"> > <li class="g-item-sortable" data-id="<ASIN>" ...>
ITEM_LIST_SELECTOR = "ul#g-items > li.g-item-sortable"
# フォールバック (data-id 構造変更時): a 要素から ASIN を抽出
ITEM_FALLBACK_LINK_SELECTOR = "ul#g-items a[href*='/dp/'], ul#g-items a[href*='/gp/product/']"

DEFAULT_INITIAL_WAIT_SEC = 25      # 初回ハイドレーション (#g-items 出現待ち)
DEFAULT_LOAD_MORE_CLICKS = 12       # 無限スクロール最大回数
DEFAULT_AFTER_SCROLL_SLEEP = 2.0
DEFAULT_MAX_ITEMS = 500             # 暴走防止ハードリミット
DEBUG_DUMP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "debug")

# Mercari と同じく visible で小さく配置 (bot 検出回避 + 作業の邪魔最小化)
DEFAULT_WINDOW_SIZE = (820, 640)
DEFAULT_WINDOW_POSITION = (60, 60)


def parse_wishlist_id(url: str) -> Optional[str]:
    """ウィッシュリスト URL から LIST_ID を抽出."""
    if not url:
        return None
    m = WISHLIST_URL_RE.search(url)
    return m.group(1) if m else None


def parse_asin(url: str) -> Optional[str]:
    """Amazon 商品 URL から ASIN (10 桁) を抽出. 一致しなければ None."""
    if not url:
        return None
    m = ASIN_RE.search(url)
    return m.group(1).upper() if m else None


def normalize_wishlist_url(url: str) -> str:
    """ウィッシュリスト URL を正規化形式 (`/hz/wishlist/ls/<ID>`) に変換.

    `?ref=nav_wishlist_lists_1` 等の suffix を取り除き、ID 部分のみ保持。
    LIST_ID が抽出できない場合は raise。
    """
    list_id = parse_wishlist_id(url)
    if not list_id:
        raise ValueError(f"ウィッシュリスト URL の形式が不正: {url}")
    return f"https://www.amazon.co.jp/hz/wishlist/ls/{list_id}"


def extract_wishlist_items_from_html(page_source: str) -> list[dict]:
    """ページ HTML から、ウィッシュリスト商品の URL/ASIN を抽出.

    優先: <li data-id="ASIN"> から取得
    フォールバック: a[href*='/dp/'] の href から ASIN 抽出

    重複は ASIN 単位で除外。
    """
    from bs4 import BeautifulSoup  # noqa: PLC0415

    soup = BeautifulSoup(page_source, "lxml")
    seen: set[str] = set()
    results: list[dict] = []

    items = soup.select(ITEM_LIST_SELECTOR)
    for li in items:
        # 1) data-id 属性 (Amazon wishlist の標準構造)
        asin = (li.get("data-id") or "").strip().upper()

        # 2) data-id が無効 → 内部 a 要素から抽出
        if not asin or len(asin) != 10:
            a = li.select_one("a[href*='/dp/'], a[href*='/gp/product/']")
            if a:
                asin = parse_asin(a.get("href") or "") or ""

        if not asin or len(asin) != 10:
            continue
        if asin in seen:
            continue
        seen.add(asin)

        # 商品 URL は /dp/<ASIN> 形式に正規化 (ref 等の付加 query を除去)
        results.append({
            "url": f"https://www.amazon.co.jp/dp/{asin}",
            "asin": asin,
        })

    # フォールバック: ul#g-items > li 構造が変わってる場合、a 要素を直接拾う
    if not results:
        anchors = soup.select(ITEM_FALLBACK_LINK_SELECTOR)
        for a in anchors:
            href = a.get("href") or ""
            asin = parse_asin(href)
            if not asin or asin in seen:
                continue
            seen.add(asin)
            results.append({
                "url": f"https://www.amazon.co.jp/dp/{asin}",
                "asin": asin,
            })

    return results


def create_driver(
    headless: bool = False,
    profile_dir: Optional[str] = None,
    window_size: Optional[tuple[int, int]] = None,
    window_position: Optional[tuple[int, int]] = None,
):
    """undetected_chromedriver を起動して返す (Amazon 用 profile)."""
    try:
        import undetected_chromedriver as uc  # noqa: PLC0415
    except ImportError as e:
        raise RuntimeError(
            "undetected_chromedriver 未インストール。pip install undetected-chromedriver"
        ) from e

    profile = profile_dir or CHROME_PROFILE_DIR
    os.makedirs(profile, exist_ok=True)

    options = uc.ChromeOptions()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--lang=ja-JP")
    options.add_argument(f"--user-data-dir={profile}")
    if headless:
        options.add_argument("--headless=new")
    else:
        ws = window_size or DEFAULT_WINDOW_SIZE
        wp = window_position or DEFAULT_WINDOW_POSITION
        options.add_argument(f"--window-size={ws[0]},{ws[1]}")
        options.add_argument(f"--window-position={wp[0]},{wp[1]}")

    driver = uc.Chrome(options=options, version_main=CHROME_VERSION_MAIN)
    if not headless:
        try:
            ws = window_size or DEFAULT_WINDOW_SIZE
            wp = window_position or DEFAULT_WINDOW_POSITION
            driver.set_window_size(ws[0], ws[1])
            driver.set_window_position(wp[0], wp[1])
        except Exception:
            pass
    return driver


def _wait_for_wishlist_anchor(driver, timeout_sec: int) -> bool:
    """ウィッシュリストの商品コンテナが現れるまで待機."""
    from selenium.webdriver.common.by import By  # noqa: PLC0415

    selectors = [
        ITEM_LIST_SELECTOR,                           # 通常: ul#g-items > li.g-item-sortable
        "ul#g-items li",                               # 構造変更フォールバック
        "ul#g-items a[href*='/dp/']",                  # 最終フォールバック
    ]

    start = time.time()
    end_at = start + timeout_sec
    scrolled = False
    while time.time() < end_at:
        for sel in selectors:
            elements = driver.find_elements(By.CSS_SELECTOR, sel)
            if elements:
                return True
        # 3 秒経過しても見つからなければ scroll で lazy-render を強制発火
        if not scrolled and time.time() - start > 3.0:
            try:
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                driver.execute_script("window.scrollTo(0, 0);")
            except Exception:
                pass
            scrolled = True
        time.sleep(0.5)
    return False


def _dump_debug_artifacts(driver, label: str) -> tuple[str, str]:
    """page_source とスクリーンショットを debug/ に保存."""
    os.makedirs(DEBUG_DUMP_DIR, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    html_path = os.path.join(DEBUG_DUMP_DIR, f"{label}_{ts}.html")
    png_path = os.path.join(DEBUG_DUMP_DIR, f"{label}_{ts}.png")
    try:
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(driver.page_source or "")
    except Exception:
        html_path = ""
    try:
        driver.save_screenshot(png_path)
    except Exception:
        png_path = ""
    return html_path, png_path


def _count_items(driver) -> int:
    from selenium.webdriver.common.by import By  # noqa: PLC0415

    return len(driver.find_elements(By.CSS_SELECTOR, ITEM_LIST_SELECTOR))


def _scroll_load_more(driver, sleep_after: float) -> bool:
    """無限スクロール 1 ステップ. 件数増えたら True、増えなければ False (末尾到達)."""
    before = _count_items(driver)
    try:
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
    except Exception:
        pass
    time.sleep(sleep_after)
    after = _count_items(driver)
    return after > before


def collect_wishlist_urls(
    wishlist_url: str,
    driver=None,
    max_items: int = DEFAULT_MAX_ITEMS,
    load_more_clicks: int = DEFAULT_LOAD_MORE_CLICKS,
    initial_wait_sec: int = DEFAULT_INITIAL_WAIT_SEC,
    after_scroll_sleep: float = DEFAULT_AFTER_SCROLL_SLEEP,
    headless: bool = False,
) -> list[dict]:
    """Amazon ウィッシュリストから URL リストを収集.

    Args:
        wishlist_url:     公開リスト URL (例: https://www.amazon.co.jp/hz/wishlist/ls/XXXXX...)
        driver:           外部から渡された driver (None なら内部生成 / 終了)
        max_items:        ハードリミット (default 500)
        load_more_clicks: 無限スクロール最大回数
        initial_wait_sec: 初回 anchor 出現待ちタイムアウト
        after_scroll_sleep: スクロール後の wait
        headless:         driver=None で生成する際の headless 指定

    Returns:
        [{"url", "asin"}, ...] (ASIN でデデュープ済)
    """
    target_url = normalize_wishlist_url(wishlist_url)

    own_driver = driver is None
    if own_driver:
        driver = create_driver(headless=headless)

    try:
        driver.get(target_url)

        if not _wait_for_wishlist_anchor(driver, initial_wait_sec):
            current_url = driver.current_url
            html_path, png_path = _dump_debug_artifacts(driver, "wishlist_no_anchor")
            raise RuntimeError(
                "ウィッシュリストの商品コンテナが初期化中に見つからない。\n"
                f"  入力 URL    : {target_url}\n"
                f"  現在の URL : {current_url}\n"
                f"  HTML dump : {html_path}\n"
                f"  Screenshot: {png_path}\n"
                "リストが「公開」になっているか確認してください。\n"
                "公開済の場合は dump HTML を確認して selector の変更有無を調査。"
            )

        # 無限スクロールで全件ロード
        for _ in range(load_more_clicks):
            grew = _scroll_load_more(driver, sleep_after=after_scroll_sleep)
            if not grew:
                break

        page_source = driver.page_source
        items = extract_wishlist_items_from_html(page_source)
        if max_items and len(items) > max_items:
            items = items[:max_items]
        return items
    finally:
        if own_driver:
            try:
                driver.quit()
            except Exception:
                pass


def collect_wishlist_with_details(
    wishlist_url: str,
    driver=None,
    max_items: int = DEFAULT_MAX_ITEMS,
    load_more_clicks: int = DEFAULT_LOAD_MORE_CLICKS,
    initial_wait_sec: int = DEFAULT_INITIAL_WAIT_SEC,
    after_scroll_sleep: float = DEFAULT_AFTER_SCROLL_SLEEP,
    headless: bool = False,
    exclude_unavailable: bool = True,
    progress_callback=None,
) -> list[dict]:
    """URL 収集 → 各商品ページを訪問して詳細を取得まで一括実行.

    Args:
        wishlist_url:        公開リスト URL
        exclude_unavailable: True で在庫切れ/取扱中止商品を除外 (in_stock=False を除外)
        progress_callback:   callable(current: int, total: int, msg: str) | None
        他: collect_wishlist_urls と同じ

    Returns:
        [
          {
            "url", "asin",
            "title", "price_jpy", "condition", "description",
            "image_urls", "in_stock", "status"
          },
          ...
        ]
        詳細取得失敗時は空欄で含める (推測で埋めない、CLAUDE.md fail-closed)。
    """
    from scrapers import amazon_item_detail  # noqa: PLC0415

    own_driver = driver is None
    if own_driver:
        driver = create_driver(headless=headless)
    try:
        url_items = collect_wishlist_urls(
            wishlist_url=wishlist_url,
            driver=driver,
            max_items=max_items,
            load_more_clicks=load_more_clicks,
            initial_wait_sec=initial_wait_sec,
            after_scroll_sleep=after_scroll_sleep,
            headless=headless,
        )

        results: list[dict] = []
        total = len(url_items)
        for i, item in enumerate(url_items, start=1):
            if progress_callback:
                try:
                    progress_callback(i, total, item["url"])
                except Exception:
                    pass
            detail = amazon_item_detail.fetch_detail(driver, item["url"])
            if detail is None:
                merged = {
                    **item,
                    "title": "",
                    "price_jpy": None,
                    "condition": "New",  # Amazon は新品が基本
                    "description": "",
                    "image_urls": [],
                    "in_stock": None,
                    "status": "UNKNOWN",
                }
            else:
                merged = {**item, **detail}

            if exclude_unavailable and merged.get("in_stock") is False:
                continue
            results.append(merged)
        return results
    finally:
        if own_driver:
            try:
                driver.quit()
            except Exception:
                pass


# ============================================================================
# CLI (動作確認用)
# ============================================================================
if __name__ == "__main__":
    import argparse
    import json

    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True, help="公開ウィッシュリスト URL")
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--max-items", type=int, default=DEFAULT_MAX_ITEMS)
    ap.add_argument("--load-more", type=int, default=DEFAULT_LOAD_MORE_CLICKS)
    ap.add_argument(
        "--dump-html",
        action="store_true",
        help="ページを開いて scroll → HTML を dump して終了 (selector 調査用)",
    )
    args = ap.parse_args()

    if args.dump_html:
        d = create_driver(headless=args.headless)
        try:
            d.get(normalize_wishlist_url(args.url))
            time.sleep(8)
            try:
                d.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            except Exception:
                pass
            time.sleep(5)
            try:
                d.execute_script("window.scrollTo(0, 0);")
            except Exception:
                pass
            time.sleep(2)
            html_path, png_path = _dump_debug_artifacts(d, "wishlist_dump")
            print(f"current url: {d.current_url}")
            print(f"html path  : {html_path}")
            print(f"screenshot : {png_path}")
        finally:
            try:
                d.quit()
            except Exception:
                pass
        raise SystemExit(0)

    result = collect_wishlist_urls(
        wishlist_url=args.url,
        max_items=args.max_items,
        load_more_clicks=args.load_more,
        headless=args.headless,
    )
    print(f"--- collected {len(result)} item(s) ---")
    print(json.dumps(result, ensure_ascii=False, indent=2))
