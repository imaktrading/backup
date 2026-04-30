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

# 2026-04-30: Mercari Web 版で /mypage/likes は廃止 (404 fallback)、
# 新 URL は /mypage/favorites (複数形). trabajo decompile 当時とは異なる.
MERCARI_LIKES_URL = "https://jp.mercari.com/mypage/favorites"
ITEM_ANCHOR_SELECTOR = "a[data-testid='mercari-liked-item']"
LOAD_MORE_BUTTON_SELECTOR = "mer-button[class*='LoadMoreButton'] > button"
GENERIC_LINK_SELECTOR = "a[href*='item/']"

# /item/m12345... または /items/m12345...
MERCARI_ITEM_RE = re.compile(r"/items?/(m\d+)")

# UA はハードコードしない. Chrome 本体の本物 UA を使うことで Mercari の
# 「お使いのブラウザがWebサイトに対応していない」検出を回避する.
# (UA に Chrome/126 等の古いバージョンを書くと version_main=146 と矛盾し、
#  Mercari 側のブラウザバージョンチェックで /mypage/likes が「ページが見つかりません」
#  にフォールバックする現象が発生 — 2026-04-30 確認済)

DEFAULT_INITIAL_WAIT_SEC = 25  # 初回ハイドレーション (mercari-liked-item 出現待ち)
DEFAULT_LOAD_MORE_CLICKS = 12  # スクロール最大回数 (1 回 ≒ 20 件 ロード想定)
DEFAULT_AFTER_CLICK_SLEEP = 2.0
DEFAULT_MAX_ITEMS = 500        # ハードリミット (暴走防止)
DEBUG_DUMP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "debug")

# Chrome ウィンドウサイズ・位置 (画面右下に小さく配置、邪魔にならないが visible で bot 検出回避)
# 完全な非表示 (minimize / headless) は Mercari に弾かれるため、小さく visible が現状の最適解.
DEFAULT_WINDOW_SIZE = (820, 640)
DEFAULT_WINDOW_POSITION = (40, 40)


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


def create_driver(
    headless: bool = False,
    profile_dir: Optional[str] = None,
    window_size: Optional[tuple[int, int]] = None,
    window_position: Optional[tuple[int, int]] = None,
):
    """undetected_chromedriver を起動して返す.

    Mercari のいいねページはログイン必須なので、初回は headless=False で手動ログイン後、
    2 回目以降は profile が再利用される。Phase 1a では headless=False をデフォルトに。

    window_size / window_position:
      ウィンドウを小さく配置することで作業中の邪魔を最小化する.
      None で DEFAULT_WINDOW_SIZE / DEFAULT_WINDOW_POSITION を使用.
      headless=True 時は無視 (画面なし).
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
    # --user-agent は意図的に指定しない (Chrome 本体の UA を使う、上部コメント参照)
    if headless:
        options.add_argument("--headless=new")
    else:
        # visible モード時のみ window-size / position を反映 (visible で小さく)
        ws = window_size or DEFAULT_WINDOW_SIZE
        wp = window_position or DEFAULT_WINDOW_POSITION
        options.add_argument(f"--window-size={ws[0]},{ws[1]}")
        options.add_argument(f"--window-position={wp[0]},{wp[1]}")

    driver = uc.Chrome(options=options, version_main=CHROME_VERSION_MAIN)
    if not headless:
        # add_argument の window-size は起動時のみ反映され、UC が後で resize する場合があるので
        # 念のため明示で再設定 (画面右下じゃなく左上にしないと visible でも作業の邪魔にしにくい)
        try:
            ws = window_size or DEFAULT_WINDOW_SIZE
            wp = window_position or DEFAULT_WINDOW_POSITION
            driver.set_window_size(ws[0], ws[1])
            driver.set_window_position(wp[0], wp[1])
        except Exception:
            pass
    return driver


def _wait_for_likes_anchor(driver, timeout_sec: int) -> bool:
    """いいねページの商品 anchor が現れるまで待機. 現れたら True。

    ハイドレーションが遅い場合に備え、3 秒経過した時点で 1 回ページ末尾までスクロール
    (lazy-render 系を強制発火) → さらに polling を継続。
    """
    from selenium.webdriver.common.by import By  # noqa: PLC0415

    selectors = [
        ITEM_ANCHOR_SELECTOR,           # a[data-testid='mercari-liked-item'] (trabajo 由来)
        GENERIC_LINK_SELECTOR,           # a[href*='item/']
        "a[href^='/item/']",             # よりタイト
        "a[href*='/items/']",            # alt path
    ]

    start = time.time()
    end_at = start + timeout_sec
    scrolled = False
    while time.time() < end_at:
        for sel in selectors:
            elements = driver.find_elements(By.CSS_SELECTOR, sel)
            # /item/ を含む href を持つ a が 1 つでもあれば OK
            for el in elements:
                href = (el.get_attribute("href") or "")
                if "/item/" in href or "/items/" in href:
                    return True
        # 3 秒経過しても見つからなければ 1 回スクロールして lazy-render を強制発火
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
    """page_source とスクリーンショットを debug/ に保存. 戻り値は (html_path, png_path)."""
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


def _count_anchors(driver) -> int:
    """現時点の mercari-liked-item anchor 数を返す (lazy-load 進捗計測用)."""
    from selenium.webdriver.common.by import By  # noqa: PLC0415

    return len(driver.find_elements(By.CSS_SELECTOR, ITEM_ANCHOR_SELECTOR))


def _scroll_or_click_load_more(driver, sleep_after: float) -> bool:
    """無限スクロール 1 ステップ実行. anchor が増えたら True、増えなければ False (= 末尾到達).

    2026-04-30: /mypage/favorites は LoadMoreButton 廃止 + 無限スクロール式に変更.
    旧「もっと見る」ボタンは存在しないが、互換のため fallback で残す.
    """
    from selenium.webdriver.common.by import By  # noqa: PLC0415
    from selenium.common.exceptions import (  # noqa: PLC0415
        ElementNotInteractableException,
        StaleElementReferenceException,
    )

    before = _count_anchors(driver)

    # 1) ページ末尾にスクロール (主要ロード方式)
    try:
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
    except Exception:
        pass

    # 2) フォールバック: もし「もっと見る」ボタンが存在すれば押す (互換維持)
    elements = driver.find_elements(By.CSS_SELECTOR, LOAD_MORE_BUTTON_SELECTOR)
    if elements and elements[0].is_displayed():
        try:
            driver.execute_script("arguments[0].click();", elements[0])
        except (ElementNotInteractableException, StaleElementReferenceException):
            pass
    else:
        for btn in driver.find_elements(By.CSS_SELECTOR, "button"):
            try:
                if (btn.text or "").strip() == "もっと見る":
                    driver.execute_script("arguments[0].click();", btn)
                    break
            except StaleElementReferenceException:
                continue

    time.sleep(sleep_after)
    after = _count_anchors(driver)
    return after > before


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
            # debug 用に page_source とスクショを保存して selector 調査の手掛かりに
            current_url = driver.current_url
            html_path, png_path = _dump_debug_artifacts(driver, "likes_no_anchor")
            raise RuntimeError(
                "いいねページの anchor が初期化中に見つからない。\n"
                f"  現在の URL : {current_url}\n"
                f"  HTML dump : {html_path}\n"
                f"  Screenshot: {png_path}\n"
                "ログイン状態を確認してください (--login で再ログイン)。\n"
                "ログイン済の場合は dump HTML を確認して selector の変更有無を調査。"
            )

        # 無限スクロールで全件ロード (anchor が増えなくなったら break = 末尾到達)
        for _ in range(load_more_clicks):
            grew = _scroll_or_click_load_more(driver, sleep_after=after_click_sleep)
            if not grew:
                break

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
    ap.add_argument(
        "--dump-html",
        action="store_true",
        help="いいねページを開いて 25s 待機 + scroll → debug/likes_dump_*.html に保存して終了 (selector 調査用)",
    )
    args = ap.parse_args()

    if args.login:
        login_interactive()
        raise SystemExit(0)

    if args.dump_html:
        # selector 調査専用: ページを開いて待機 + scroll してから page_source を保存
        d = create_driver(headless=args.headless)
        try:
            d.get(MERCARI_LIKES_URL)
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
            html_path, png_path = _dump_debug_artifacts(d, "likes_dump")
            print(f"current url: {d.current_url}")
            print(f"html path  : {html_path}")
            print(f"screenshot : {png_path}")
        finally:
            try:
                d.quit()
            except Exception:
                pass
        raise SystemExit(0)

    result = collect_liked_urls(
        max_items=args.max_items,
        load_more_clicks=args.load_more,
        headless=args.headless,
    )
    print(f"--- collected {len(result)} item(s) ---")
    print(json.dumps(result, ensure_ascii=False, indent=2))
