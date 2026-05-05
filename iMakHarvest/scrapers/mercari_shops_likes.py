"""mercari_shops_likes - Mercari Shops いいね商品の URL 収集 (Selenium ベース).

通常 Mercari の `mercari_likes.py` の Shops 版。Mercari 通常品コードは一切 import せず
独立 (Phase 1c Amazon と同じ分離パターン)。

設計原則 (Phase 1b 着手時 DOM 確認結果反映):
  - いいねページは通常 Mercari と同じ /mypage/favorites
  - Shops anchor は data-testid="shops-liked-item" (通常品 "mercari-liked-item" と別)
  - URL slug: /shops/product/<22 文字英数字>
  - スクロールで lazy-load (通常 Mercari と同じ動作)
  - chrome profile は通常 Mercari と共有 (同じログインセッション、`chrome_profile_mercari`)
    別 profile にすると再ログインが必要になり手間

返却形式:
    [
      {"url": "https://jp.mercari.com/shops/product/2JNysv3RcsZP37Dt8Zoaof",
       "shop_product_id": "2JNysv3RcsZP37Dt8Zoaof"},
      ...
    ]
"""
from __future__ import annotations

import os
import re
import time
from typing import Optional

# 通常 Mercari と同じ chrome profile を再利用 (ログインセッション共有)
CHROME_PROFILE_DIR = r"C:\Users\imax2\local_data\iMakHarvest\chrome_profile_mercari"
CHROME_VERSION_MAIN = 146

# 通常 Mercari と同じいいねページ (Shops も混在)
MERCARI_LIKES_URL = "https://jp.mercari.com/mypage/favorites"

# Shops anchor 専用 selector (DOM 確認 2026-05-06 結果)
SHOPS_ANCHOR_SELECTOR = "a[data-testid='shops-liked-item']"
# フォールバック: testid 仕様変更時に href から拾う
SHOPS_GENERIC_LINK_SELECTOR = "a[href*='/shops/product/']"

# Shops product URL → slug 抽出
SHOPS_PRODUCT_RE = re.compile(r"/shops/product/([A-Za-z0-9]+)")

DEFAULT_INITIAL_WAIT_SEC = 25
DEFAULT_LOAD_MORE_CLICKS = 12
DEFAULT_AFTER_CLICK_SLEEP = 2.0
DEFAULT_MAX_ITEMS = 500
DEBUG_DUMP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "debug")

DEFAULT_WINDOW_SIZE = (820, 640)
DEFAULT_WINDOW_POSITION = (40, 40)


def parse_shop_product_id(url: str) -> Optional[str]:
    """Shops product URL から slug を抽出. 通常 Mercari /item/ は対象外."""
    if not url:
        return None
    m = SHOPS_PRODUCT_RE.search(url)
    return m.group(1) if m else None


def extract_shops_likes_from_html(page_source: str) -> list[dict]:
    """page_source から Shops いいね商品の URL/slug を抽出 (BeautifulSoup ベース、テスト容易).

    1. data-testid="shops-liked-item" の anchor を優先
    2. fallback: a[href*='/shops/product/']
    重複は slug 単位で除外。
    """
    from bs4 import BeautifulSoup  # noqa: PLC0415

    soup = BeautifulSoup(page_source, "lxml")
    seen: set[str] = set()
    results: list[dict] = []

    anchors = soup.select(SHOPS_ANCHOR_SELECTOR)
    if not anchors:
        anchors = soup.select(SHOPS_GENERIC_LINK_SELECTOR)

    for a in anchors:
        href = (a.get("href") or "").strip()
        if not href:
            continue
        if href.startswith("/"):
            href = f"https://jp.mercari.com{href}"
        slug = parse_shop_product_id(href)
        if not slug:
            continue
        if slug in seen:
            continue
        seen.add(slug)
        results.append({"url": href, "shop_product_id": slug})
    return results


def create_driver(
    headless: bool = False,
    profile_dir: Optional[str] = None,
    window_size: Optional[tuple[int, int]] = None,
    window_position: Optional[tuple[int, int]] = None,
):
    """undetected_chromedriver を起動 (通常 Mercari と同じ profile を共有).

    通常 Mercari と並行運用しないなら同 profile で OK。
    並行起動するならエラーになるため、`mercari_shops_likes` 単独で driver を起動する想定。
    """
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


def _wait_for_shops_anchor(driver, timeout_sec: int) -> bool:
    """Shops anchor が現れるまで待機.

    通常 Mercari の anchor が先に出る場合があるが、Shops が混在するページなので
    Shops anchor が 0 件 = ハイドレーション未完了 or Shops が無いだけ。
    Shops が無い場合 (通常品のみのアカウント) は false を返す → caller 側で空リスト扱い。
    """
    from selenium.webdriver.common.by import By  # noqa: PLC0415

    selectors = [
        SHOPS_ANCHOR_SELECTOR,
        SHOPS_GENERIC_LINK_SELECTOR,
    ]

    start = time.time()
    end_at = start + timeout_sec
    scrolled = False
    while time.time() < end_at:
        # 通常品 anchor または Shops anchor のいずれかが出れば「ハイドレーション完了」とみなす
        # (Shops が 0 件のアカウントでも適切に終了するため)
        anchors_any = driver.find_elements(
            By.CSS_SELECTOR,
            "a[data-testid='mercari-liked-item'], a[data-testid='shops-liked-item']",
        )
        if anchors_any:
            # Shops が見つかれば確定
            for sel in selectors:
                if driver.find_elements(By.CSS_SELECTOR, sel):
                    return True
            # 通常品のみ = Shops 0 件、待ち続けない
            return False
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


def _count_shops_anchors(driver) -> int:
    from selenium.webdriver.common.by import By  # noqa: PLC0415

    return len(driver.find_elements(By.CSS_SELECTOR, SHOPS_ANCHOR_SELECTOR))


def _scroll_load_more(driver, sleep_after: float) -> bool:
    """無限スクロール 1 ステップ. Shops anchor が増えたら True、増えなければ False."""
    before = _count_shops_anchors(driver)
    try:
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
    except Exception:
        pass
    time.sleep(sleep_after)
    after = _count_shops_anchors(driver)
    return after > before


def collect_shops_liked_urls(
    driver=None,
    max_items: int = DEFAULT_MAX_ITEMS,
    load_more_clicks: int = DEFAULT_LOAD_MORE_CLICKS,
    initial_wait_sec: int = DEFAULT_INITIAL_WAIT_SEC,
    after_click_sleep: float = DEFAULT_AFTER_CLICK_SLEEP,
    headless: bool = False,
) -> list[dict]:
    """Mercari Shops いいねページから URL リストを収集.

    Args / Returns: mercari_likes.collect_liked_urls と同じ構造.
    Shops が 1 件も無いアカウント → 空リスト返却 (raise しない、通常運用扱い)。
    """
    own_driver = driver is None
    if own_driver:
        driver = create_driver(headless=headless)

    try:
        driver.get(MERCARI_LIKES_URL)

        if not _wait_for_shops_anchor(driver, initial_wait_sec):
            # Shops が無い (Shops 0 件アカウント) もハイドレーション失敗もここに来るが、
            # Shops 0 件は正常動作なので空リスト返却。判別は「いいねページに着けたか」で。
            try:
                from selenium.webdriver.common.by import By  # noqa: PLC0415
                # 通常品 anchor が見つかれば、Shops 0 件として正常終了
                if driver.find_elements(By.CSS_SELECTOR, "a[data-testid='mercari-liked-item']"):
                    return []
            except Exception:
                pass
            current_url = driver.current_url
            html_path, png_path = _dump_debug_artifacts(driver, "shops_likes_no_anchor")
            raise RuntimeError(
                "Shops いいね anchor が初期化中に見つからない (通常品 anchor も無し)。\n"
                f"  現在の URL : {current_url}\n"
                f"  HTML dump : {html_path}\n"
                f"  Screenshot: {png_path}\n"
                "ログイン状態を確認してください。"
            )

        for _ in range(load_more_clicks):
            grew = _scroll_load_more(driver, sleep_after=after_click_sleep)
            if not grew:
                break

        page_source = driver.page_source
        items = extract_shops_likes_from_html(page_source)
        if max_items and len(items) > max_items:
            items = items[:max_items]
        return items
    finally:
        if own_driver:
            try:
                driver.quit()
            except Exception:
                pass


def collect_shops_likes_with_details(
    driver=None,
    max_items: int = DEFAULT_MAX_ITEMS,
    load_more_clicks: int = DEFAULT_LOAD_MORE_CLICKS,
    initial_wait_sec: int = DEFAULT_INITIAL_WAIT_SEC,
    after_click_sleep: float = DEFAULT_AFTER_CLICK_SLEEP,
    headless: bool = False,
    exclude_sold: bool = True,
    progress_callback=None,
) -> list[dict]:
    """URL 収集 → 各商品ページ訪問して詳細取得まで一括.

    取得フィールド: title / price_jpy / condition / description / image_urls /
                  in_stock / status / size / color (size は常に空、Shops に field 無し)
    """
    from scrapers import mercari_shops_item_detail  # noqa: PLC0415

    own_driver = driver is None
    if own_driver:
        driver = create_driver(headless=headless)
    try:
        url_items = collect_shops_liked_urls(
            driver=driver,
            max_items=max_items,
            load_more_clicks=load_more_clicks,
            initial_wait_sec=initial_wait_sec,
            after_click_sleep=after_click_sleep,
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
            detail = mercari_shops_item_detail.fetch_detail(driver, item["url"])
            if detail is None:
                merged = {
                    **item,
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
            else:
                merged = {**item, **detail}

            if exclude_sold and merged.get("in_stock") is False:
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
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--max-items", type=int, default=DEFAULT_MAX_ITEMS)
    ap.add_argument("--load-more", type=int, default=DEFAULT_LOAD_MORE_CLICKS)
    args = ap.parse_args()

    result = collect_shops_liked_urls(
        max_items=args.max_items,
        load_more_clicks=args.load_more,
        headless=args.headless,
    )
    print(f"--- collected {len(result)} shops item(s) ---")
    print(json.dumps(result, ensure_ascii=False, indent=2))
