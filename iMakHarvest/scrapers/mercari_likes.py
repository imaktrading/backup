"""mercari_likes - メルカリ「いいね一覧」から商品 URL を収集 (Selenium ベース).

trabajo `getMercariUrls` の Python 移植 + 簡略化版:

- 入口 URL: https://jp.mercari.com/mypage/likes (要ログイン)
- アンカー: a[data-testid='mercari-liked-item']
- 「もっと見る」ボタン (mer-button[class*='LoadMoreButton'] > button) を最大 N 回押下
- 取得した a タグから href を集めて item_id (m\\d+) をパース
- 重複は item_id 単位で除外
- データ取得は URL のみ (title/price は商品ページ訪問が必要なので Phase 1a では取らない)

設計原則:
  - Phase 1a スコープ: URL 収集だけ (在庫判定は iMakInventory に任せる)
  - Chrome profile は iMakInventory と分離 (concurrent lock 回避)
  - --login モードで初回手動ログイン (cookie 永続化されるので 2 回目以降は自動)
  - 失敗時は raise (caller が retry/log を判断)

返却形式:
    [
      {"url": "https://jp.mercari.com/item/m12345...", "item_id": "m12345..."},
      ...
    ]
"""
from __future__ import annotations

import os
import re
import time
from typing import Optional

CHROME_PROFILE_DIR = r"C:\Users\imax2\local_data\iMakHarvest\chrome_profile_mercari"
CHROME_VERSION_MAIN = 146

MERCARI_LIKES_URL = "https://jp.mercari.com/mypage/likes"
ITEM_ANCHOR_SELECTOR = "a[data-testid='mercari-liked-item']"
LOAD_MORE_BUTTON_SELECTOR = "mer-button[class*='LoadMoreButton'] > button"
GENERIC_LINK_SELECTOR = "a[href*='item/']"

# /item/m12345... または /items/m12345...
MERCARI_ITEM_RE = re.compile(r"/items?/(m\d+)")

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)

DEFAULT_INITIAL_WAIT_SEC = 15  # 初回ハイドレーション (mercari-liked-item 出現待ち)
DEFAULT_LOAD_MORE_CLICKS = 6   # 「もっと見る」ボタン最大押下回数 (= 100 件以上を狙う)
DEFAULT_AFTER_CLICK_SLEEP = 3.0
DEFAULT_MAX_ITEMS = 200        # ハードリミット (暴走防止)


def parse_item_id(url: str) -> Optional[str]:
    """メルカリ商品 URL から item_id (m\\d+) を抽出. shop/product は対象外 (本モジュールは通常品のみ)."""
    if not url:
        return None
    m = MERCARI_ITEM_RE.search(url)
    if m:
        return m.group(1)
    return None


def extract_likes_from_html(page_source: str) -> list[dict]:
    """ページ HTML から、いいね商品の URL/item_id を抽出.

    a[data-testid='mercari-liked-item'] の href を取り、item_id でデデュープ。
    トップレベル page_source 全体を BeautifulSoup でパースするのでテストで使いやすい。
    """
    from bs4 import BeautifulSoup  # noqa: PLC0415

    soup = BeautifulSoup(page_source, "lxml")
    seen: set[str] = set()
    results: list[dict] = []
    # 1) data-testid 付きの厳密セレクタ
    anchors = soup.select(ITEM_ANCHOR_SELECTOR)
    # 2) フォールバック: data-testid が外れた場合に備え a[href*='item/'] でも回収
    if not anchors:
        anchors = soup.select(GENERIC_LINK_SELECTOR)

    for a in anchors:
        href = (a.get("href") or "").strip()
        if not href:
            continue
        # 相対 URL を絶対化
        if href.startswith("/"):
            href = f"https://jp.mercari.com{href}"
        item_id = parse_item_id(href)
        if not item_id:
            continue
        if item_id in seen:
            continue
        seen.add(item_id)
        results.append({"url": href, "item_id": item_id})
    return results


def create_driver(headless: bool = False, profile_dir: Optional[str] = None):
    """undetected_chromedriver を起動して返す.

    Mercari のいいねページはログイン必須なので、初回は headless=False で手動ログイン後、
    2 回目以降は profile が再利用される。Phase 1a では headless=False をデフォルトに。
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
    options.add_argument(f"--user-agent={USER_AGENT}")
    if headless:
        options.add_argument("--headless=new")

    return uc.Chrome(options=options, version_main=CHROME_VERSION_MAIN)


def _wait_for_likes_anchor(driver, timeout_sec: int) -> bool:
    """a[data-testid='mercari-liked-item'] が現れるまで待機. 現れたら True。"""
    from selenium.webdriver.common.by import By  # noqa: PLC0415

    end_at = time.time() + timeout_sec
    while time.time() < end_at:
        elements = driver.find_elements(By.CSS_SELECTOR, ITEM_ANCHOR_SELECTOR)
        if elements:
            return True
        # フォールバック: data-testid が変わった場合
        elements = driver.find_elements(By.CSS_SELECTOR, GENERIC_LINK_SELECTOR)
        if elements:
            return True
        time.sleep(0.5)
    return False


def _click_load_more(driver) -> bool:
    """「もっと見る」ボタンを 1 回押す. 押せたら True、ボタン無し / 不可視なら False."""
    from selenium.webdriver.common.by import By  # noqa: PLC0415
    from selenium.common.exceptions import (  # noqa: PLC0415
        ElementNotInteractableException,
        StaleElementReferenceException,
    )

    # 1) data-testid / class 付きの公式ボタン
    elements = driver.find_elements(By.CSS_SELECTOR, LOAD_MORE_BUTTON_SELECTOR)
    if elements and elements[0].is_displayed():
        try:
            driver.execute_script("arguments[0].click();", elements[0])
            return True
        except (ElementNotInteractableException, StaleElementReferenceException):
            return False

    # 2) フォールバック: 「もっと見る」テキストの button 要素を全件チェック
    buttons = driver.find_elements(By.CSS_SELECTOR, "button")
    for btn in buttons:
        try:
            if (btn.text or "").strip() == "もっと見る":
                driver.execute_script("arguments[0].click();", btn)
                return True
        except StaleElementReferenceException:
            continue
    return False


def collect_liked_urls(
    driver=None,
    max_items: int = DEFAULT_MAX_ITEMS,
    load_more_clicks: int = DEFAULT_LOAD_MORE_CLICKS,
    initial_wait_sec: int = DEFAULT_INITIAL_WAIT_SEC,
    after_click_sleep: float = DEFAULT_AFTER_CLICK_SLEEP,
    headless: bool = False,
) -> list[dict]:
    """Mercari いいねページから URL リストを収集して返す.

    Args:
        driver:           外部から渡された Selenium driver (再利用、推奨)。
                          None なら内部で起動 / 終了
        max_items:        ハードリミット (default 200)
        load_more_clicks: 「もっと見る」最大押下回数
        initial_wait_sec: 初回 anchor 出現待ちのタイムアウト
        after_click_sleep: 押下後の追加 wait
        headless:         driver=None で生成する際の headless 指定

    Returns:
        [{"url", "item_id"}, ...] (item_id でデデュープ済)
    """
    own_driver = driver is None
    if own_driver:
        driver = create_driver(headless=headless)

    try:
        driver.get(MERCARI_LIKES_URL)

        if not _wait_for_likes_anchor(driver, initial_wait_sec):
            # ログイン画面に飛ばされた、もしくは DOM 仕様変更
            # → 空リストを返さず raise (誤って空書込しない)
            current_url = driver.current_url
            raise RuntimeError(
                "いいねページの anchor が初期化中に見つからない。"
                f"現在の URL: {current_url}\n"
                "ログイン状態を確認してください (--login で再ログイン)。"
            )

        # 「もっと見る」を最大 N 回押下
        for _ in range(load_more_clicks):
            clicked = _click_load_more(driver)
            if not clicked:
                break
            time.sleep(after_click_sleep)

        page_source = driver.page_source
        items = extract_likes_from_html(page_source)
        if max_items and len(items) > max_items:
            items = items[:max_items]
        return items
    finally:
        if own_driver:
            try:
                driver.quit()
            except Exception:
                pass


def login_interactive(profile_dir: Optional[str] = None) -> None:
    """初回ログイン用. Chrome を非 headless で立ち上げ、ユーザーが手動でログインするのを待つ.

    使い方:
        python -m scrapers.mercari_likes --login
    ログイン後 profile に cookie が保存され、以降の collect_liked_urls() は自動。
    """
    driver = create_driver(headless=False, profile_dir=profile_dir)
    try:
        driver.get(MERCARI_LIKES_URL)
        print("Chrome が開きました。手動でログインを完了してください。")
        print("ログインが終わったら、いいねページが表示されることを確認してから")
        print("このターミナルで Enter を押してください。")
        input(">>> Enter to finish login: ")
    finally:
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
    ap.add_argument("--login", action="store_true", help="ログイン用 Chrome を起動して終了")
    ap.add_argument("--headless", action="store_true", help="headless で実行 (login 後のみ推奨)")
    ap.add_argument("--max-items", type=int, default=DEFAULT_MAX_ITEMS)
    ap.add_argument("--load-more", type=int, default=DEFAULT_LOAD_MORE_CLICKS)
    args = ap.parse_args()

    if args.login:
        login_interactive()
        raise SystemExit(0)

    result = collect_liked_urls(
        max_items=args.max_items,
        load_more_clicks=args.load_more,
        headless=args.headless,
    )
    print(f"--- collected {len(result)} item(s) ---")
    print(json.dumps(result, ensure_ascii=False, indent=2))
