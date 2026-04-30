"""mercari_item_detail - メルカリ通常品 (/item/m...) ページから商品詳細を取得.

trabajo decompile (FormScraping.cs) + iMakInventory/scrapers/mercari_scraper.py
を参考に、いいね収集後の各 URL を訪問して以下を抽出する:

  - title         : 商品タイトル
  - price_jpy     : 価格 (整数 円)
  - condition     : 商品状態 (例: "目立った傷や汚れなし")
  - description   : 商品説明 (改行を含むプレーンテキスト)
  - image_urls    : 画像 URL のリスト
  - in_stock      : True (購入可) / False (SOLD = 売切 / 取引中)

設計原則:
  - driver は呼出側から再利用 (loop で使い回し、起動コスト削減)
  - 取得失敗時は None / 空文字 (スプシ書込時に空欄になる)
  - SOLD 商品は in_stock=False で返し、呼出側で除外判定
  - 失敗判定 (404 / 削除済 / DOM 解析不能) も return None で表現
"""
from __future__ import annotations

import re
import time
from typing import Optional

# 通常 item URL pattern (/item/m12345...)
ITEM_PATH_RE = re.compile(r"/items?/(m\d+)")

# 在庫判定の selector / マーカー (iMakInventory mercari_scraper から流用)
CHECKOUT_CONTAINER_SELECTOR = '[data-testid="checkout-button-container"]'
CHECKOUT_BUTTON_SELECTOR = '[data-testid="checkout-button"]'

# 削除済 / 取下げ済ページの body text マーカー
DELETION_KEYWORDS = (
    "商品が見つかりません",
    "削除されました",
    "削除されています",
    "該当する商品は",
    "ページが見つかりません",
    "エラーが発生しました",
    "Not Found",
)

# title 抽出候補 testid (新 DOM で何度か変わっているので複数試行)
TITLE_TESTID_CANDIDATES = ("name", "item-name", "display-name")
PRICE_TESTID_CANDIDATES = ("price", "product-price", "item-price")
CONDITION_TESTID = "商品の状態"  # 日本語文字列

DETAIL_WAIT_SEC = 20
DETAIL_POLL_INTERVAL = 0.5


def fetch_detail(driver, url: str) -> Optional[dict]:
    """driver で url を開いて商品詳細を取得.

    Returns:
        dict {
            "title": str,
            "price_jpy": int | None,
            "condition": str,
            "description": str,
            "image_urls": list[str],
            "in_stock": bool,
            "status": "ON_SALE" | "SOLD_OUT" | "DELETED",
        }
        または None (DOM 解析不能 / page load 失敗)
    """
    from selenium.webdriver.common.by import By  # noqa: PLC0415
    from selenium.common.exceptions import (  # noqa: PLC0415
        NoSuchElementException,
        WebDriverException,
    )

    try:
        driver.get(url)
    except WebDriverException:
        return None

    # checkout-button-container 出現待ち or 削除キーワード出現待ち
    container_found = False
    deleted = False
    end_at = time.time() + DETAIL_WAIT_SEC
    while time.time() < end_at:
        try:
            driver.find_element(By.CSS_SELECTOR, CHECKOUT_CONTAINER_SELECTOR)
            container_found = True
            break
        except NoSuchElementException:
            pass
        try:
            body_text = driver.find_element(By.TAG_NAME, "body").text or ""
            if any(kw in body_text for kw in DELETION_KEYWORDS):
                deleted = True
                break
        except Exception:
            pass
        time.sleep(DETAIL_POLL_INTERVAL)

    if deleted:
        return {
            "title": "",
            "price_jpy": None,
            "condition": "",
            "description": "",
            "image_urls": [],
            "in_stock": False,
            "status": "DELETED",
        }
    if not container_found:
        return None

    # 在庫判定 (checkout-button の class / name 属性で判定)
    in_stock: Optional[bool] = None
    try:
        container = driver.find_element(By.CSS_SELECTOR, CHECKOUT_CONTAINER_SELECTOR)
    except NoSuchElementException:
        return None

    try:
        btn_div = container.find_element(By.CSS_SELECTOR, CHECKOUT_BUTTON_SELECTOR)
        cls = (btn_div.get_attribute("class") or "").lower()
        name_attr = (btn_div.get_attribute("name") or "").lower()
        if "disabled__" in cls or name_attr == "disabled":
            in_stock = False
        elif name_attr == "purchase":
            in_stock = True
    except NoSuchElementException:
        # checkout-button 不在 = 取引中などで SOLD 扱い
        in_stock = False

    if in_stock is None:
        # 新パターン → 安全側で None
        return None

    title = _extract_title(driver)
    price_jpy = _extract_price(driver)
    condition = _extract_condition(driver)
    description = _extract_description(driver)
    image_urls = _extract_image_urls(driver)

    return {
        "title": title,
        "price_jpy": price_jpy,
        "condition": condition,
        "description": description,
        "image_urls": image_urls,
        "in_stock": bool(in_stock),
        "status": "ON_SALE" if in_stock else "SOLD_OUT",
    }


# ============================================================================
# 個別 field 抽出
# ============================================================================
def _extract_title(driver) -> str:
    from selenium.webdriver.common.by import By  # noqa: PLC0415

    for tid in TITLE_TESTID_CANDIDATES:
        try:
            elem = driver.find_element(By.CSS_SELECTOR, f'[data-testid="{tid}"]')
            t = (elem.text or "").strip()
            if t:
                return t
        except Exception:
            continue
    # フォールバック: h1 / mer-heading
    for sel in ("h1", "mer-heading"):
        try:
            elem = driver.find_element(By.CSS_SELECTOR, sel)
            t = (elem.text or "").strip()
            if t:
                return t
        except Exception:
            continue
    return ""


def _extract_price(driver) -> Optional[int]:
    from selenium.webdriver.common.by import By  # noqa: PLC0415

    for tid in PRICE_TESTID_CANDIDATES:
        try:
            elem = driver.find_element(By.CSS_SELECTOR, f'[data-testid="{tid}"]')
            txt = (elem.text or "").strip()
            m = re.search(r"([\d,]+)", txt)
            if m:
                try:
                    return int(m.group(1).replace(",", ""))
                except ValueError:
                    pass
        except Exception:
            continue
    return None


def _extract_condition(driver) -> str:
    from selenium.webdriver.common.by import By  # noqa: PLC0415

    # span[data-testid='商品の状態'] (trabajo パターン)
    try:
        elem = driver.find_element(By.CSS_SELECTOR, f'span[data-testid="{CONDITION_TESTID}"]')
        return (elem.text or "").strip()
    except Exception:
        pass
    # フォールバック: 「商品の状態」というテキストを持つ dt / span を探して隣の値を取る
    try:
        # 全 span から商品の状態キーワード相当のものを近似
        spans = driver.find_elements(By.TAG_NAME, "span")
        for s in spans:
            try:
                if s.get_attribute("data-testid") == CONDITION_TESTID:
                    return (s.text or "").strip()
            except Exception:
                continue
    except Exception:
        pass
    return ""


def _extract_description(driver) -> str:
    from selenium.webdriver.common.by import By  # noqa: PLC0415

    for sel in (
        'pre[data-testid="description"]',
        '[data-testid="description"]',
        "mer-show-more",
    ):
        try:
            elem = driver.find_element(By.CSS_SELECTOR, sel)
            t = (elem.text or "").strip()
            if t:
                return t
        except Exception:
            continue
    return ""


def _extract_image_urls(driver) -> list[str]:
    from selenium.webdriver.common.by import By  # noqa: PLC0415

    # trabajo: .slick-list button mer-item-thumbnail or .slick-list button img
    urls: list[str] = []
    seen: set[str] = set()
    selectors = (
        ".slick-list button mer-item-thumbnail",
        ".slick-list button img",
        "img[data-testid='item-image']",
        "img[src*='static.mercdn.net']",  # フォールバック
    )
    for sel in selectors:
        try:
            elements = driver.find_elements(By.CSS_SELECTOR, sel)
        except Exception:
            elements = []
        for e in elements:
            try:
                src = e.get_attribute("src") or e.get_attribute("data-src") or ""
            except Exception:
                src = ""
            src = (src or "").strip()
            if not src:
                continue
            if src in seen:
                continue
            seen.add(src)
            urls.append(src)
        if urls:
            break  # 最初に当たった selector で十分なら終了
    return urls


# ============================================================================
# CLI (動作確認用)
# ============================================================================
if __name__ == "__main__":
    import json
    import sys

    from scrapers.mercari_likes import create_driver

    test_url = sys.argv[1] if len(sys.argv) > 1 else (
        "https://jp.mercari.com/item/m59277919762"
    )
    print(f"--- detail: {test_url} ---")
    d = create_driver(headless=False)
    try:
        info = fetch_detail(d, test_url)
    finally:
        try:
            d.quit()
        except Exception:
            pass
    if info is None:
        print("  ⚠️ 判定不能")
        sys.exit(1)
    # description を切り詰めて表示
    info_disp = dict(info)
    info_disp["description"] = (info_disp["description"] or "")[:120]
    info_disp["image_urls"] = info_disp["image_urls"][:3]
    print(json.dumps(info_disp, ensure_ascii=False, indent=2))
