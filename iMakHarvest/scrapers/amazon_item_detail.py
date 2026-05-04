"""amazon_item_detail - Amazon 商品ページから詳細情報を取得.

mercari_item_detail の Amazon 版。Mercari コードは一切 import せず独立。

抽出フィールド:
  - title         : 商品タイトル (#productTitle)
  - price_jpy     : 価格 (整数 円)
  - condition     : "New" 固定 (Amazon ウィッシュリストは新品が基本)
  - description   : 商品説明文 (#productDescription)。無ければ feature bullets で代替
  - image_urls    : 画像 URL のリスト
  - in_stock      : True (購入可) / False (在庫切れ・取扱中止) / None (判定不能)

設計原則:
  - driver は呼出側から再利用 (loop で使い回し、起動コスト削減)
  - 取得失敗時は None / 空文字 (スプシ書込時に空欄になる)
  - in_stock は #availability の text と #add-to-cart-button 存在で判定
  - CAPTCHA 検出ページは status="CAPTCHA" で返し、上位に通知
"""
from __future__ import annotations

import re
import time
from typing import Optional

DETAIL_WAIT_SEC = 20
DETAIL_POLL_INTERVAL = 0.5

# 主要セレクタ
TITLE_SELECTOR = "#productTitle"
ADD_TO_CART_SELECTOR = "#add-to-cart-button"
BUY_NOW_SELECTOR = "#buy-now-button"
AVAILABILITY_SELECTOR = "#availability"
PRODUCT_DESCRIPTION_SELECTOR = "#productDescription"
FEATURE_BULLETS_SELECTOR = "#feature-bullets ul li"
LANDING_IMAGE_SELECTOR = "#landingImage"
ALT_IMAGES_SELECTOR = "#altImages img"
IMAGE_BLOCK_DATA_SELECTOR = "#imageBlock_feature_div"

# 画像 base ID 抽出: /images/I/<BASE_ID>(._<modifier>)?.<ext>
# BASE_ID 部分が商品画像のユニーク識別子。._AC_SY355_ などの size modifier は剥がす。
_AMAZON_IMAGE_BASE_RE = re.compile(
    r"/images/I/([A-Za-z0-9+\-]+?)(?:\._[^/]+)?\.(?:jpg|jpeg|png|webp)",
    re.IGNORECASE,
)

# 価格セレクタ候補 (Amazon の価格 DOM は版によって変わる)
PRICE_SELECTORS = (
    "#corePrice_feature_div .a-price .a-offscreen",
    "#corePriceDisplay_desktop_feature_div .a-price .a-offscreen",
    "#priceblock_ourprice",
    "#priceblock_dealprice",
    "#priceblock_saleprice",
    ".a-price .a-offscreen",
)

# 在庫切れ / 取扱中止 マーカー
UNAVAILABLE_KEYWORDS = (
    "現在在庫切れです",
    "在庫切れ",
    "ただいま在庫切れ",
    "この商品は現在お取り扱いできません",
    "お取り扱いできません",
    "出品者は現在この商品を出品していません",
    "Currently unavailable",
    "Out of Stock",
    "Out of stock",
)

# CAPTCHA / robot check ページ
CAPTCHA_KEYWORDS = (
    "Type the characters you see in this image",
    "ロボットではないことを確認",
    "Enter the characters you see below",
    "Sorry, we just need to make sure",
)

# 削除済 / not found
DELETION_KEYWORDS = (
    "Looking for something",
    "申し訳ありません。お探しのページが見つかりません",
    "ページが見つかりません",
    "お探しのページを表示できません",
    "Page Not Found",
    "Looking for something?",
)


def fetch_detail(driver, url: str) -> Optional[dict]:
    """driver で url を開いて商品詳細を取得.

    Returns:
        dict {
            "title": str,
            "price_jpy": int | None,
            "condition": "New",
            "description": str,
            "image_urls": list[str],
            "in_stock": bool | None,
            "status": "ON_SALE" | "OUT_OF_STOCK" | "DELETED" | "CAPTCHA" | "UNKNOWN",
        }
        または None (page load 失敗 / 完全に解析不能)
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

    # productTitle 出現 / 削除キーワード / CAPTCHA / 在庫切れ のいずれか確定するまで待機
    title_found = False
    deleted = False
    captcha = False
    end_at = time.time() + DETAIL_WAIT_SEC
    while time.time() < end_at:
        try:
            driver.find_element(By.CSS_SELECTOR, TITLE_SELECTOR)
            title_found = True
            break
        except NoSuchElementException:
            pass

        # body text で deletion / captcha 判定
        try:
            body_text = driver.find_element(By.TAG_NAME, "body").text or ""
        except Exception:
            body_text = ""
        if body_text:
            if any(kw in body_text for kw in CAPTCHA_KEYWORDS):
                captcha = True
                break
            if any(kw in body_text for kw in DELETION_KEYWORDS):
                deleted = True
                break
        time.sleep(DETAIL_POLL_INTERVAL)

    if captcha:
        return {
            "title": "",
            "price_jpy": None,
            "condition": "New",
            "description": "",
            "image_urls": [],
            "in_stock": None,
            "status": "CAPTCHA",
        }
    if deleted:
        return {
            "title": "",
            "price_jpy": None,
            "condition": "New",
            "description": "",
            "image_urls": [],
            "in_stock": False,
            "status": "DELETED",
        }
    if not title_found:
        return None

    title = _extract_title(driver)
    price_jpy = _extract_price(driver)
    description = _extract_description(driver)
    image_urls = _extract_image_urls(driver)
    in_stock, status = _judge_stock(driver)

    return {
        "title": title,
        "price_jpy": price_jpy,
        "condition": "New",  # Amazon ウィッシュリストは新品基準
        "description": description,
        "image_urls": image_urls,
        "in_stock": in_stock,
        "status": status,
    }


# ============================================================================
# 個別 field 抽出
# ============================================================================
def _extract_title(driver) -> str:
    from selenium.webdriver.common.by import By  # noqa: PLC0415

    try:
        elem = driver.find_element(By.CSS_SELECTOR, TITLE_SELECTOR)
        return (elem.text or "").strip()
    except Exception:
        return ""


def _extract_price(driver) -> Optional[int]:
    """Amazon 価格 DOM から円価格 (int) を抽出. 見つからない or parse 失敗で None."""
    from selenium.webdriver.common.by import By  # noqa: PLC0415

    for sel in PRICE_SELECTORS:
        try:
            elements = driver.find_elements(By.CSS_SELECTOR, sel)
        except Exception:
            elements = []
        for el in elements:
            try:
                txt = (el.get_attribute("textContent") or el.text or "").strip()
            except Exception:
                txt = ""
            if not txt:
                continue
            # "￥1,980" / "¥1,980" / "1980 円" / "$19.99" 等から数字部分のみ抽出
            # 円表記 (\￥|¥|円) を含むものを優先 (USD 表示の誤抽出回避)
            if not re.search(r"[￥¥円]", txt):
                continue
            m = re.search(r"([\d,]+)", txt)
            if m:
                try:
                    return int(m.group(1).replace(",", ""))
                except ValueError:
                    continue
    return None


def _extract_description(driver) -> str:
    """商品説明文を取得. #productDescription を優先、無ければ feature bullets で代替."""
    from selenium.webdriver.common.by import By  # noqa: PLC0415

    # 1) #productDescription (本文)
    try:
        elem = driver.find_element(By.CSS_SELECTOR, PRODUCT_DESCRIPTION_SELECTOR)
        t = (elem.text or "").strip()
        if t:
            return t
    except Exception:
        pass

    # 2) feature bullets (商品の特徴箇条書き)
    try:
        elements = driver.find_elements(By.CSS_SELECTOR, FEATURE_BULLETS_SELECTOR)
        bullets: list[str] = []
        for el in elements:
            try:
                t = (el.text or "").strip()
            except Exception:
                t = ""
            if t and "詳細を見る" not in t:
                bullets.append(f"・{t}")
        if bullets:
            return "\n".join(bullets)
    except Exception:
        pass

    return ""


def amazon_image_base_id(url: str) -> str:
    """Amazon 画像 URL から base ID を抽出 (size modifier を除いた商品画像識別子).

    例:
      .../images/I/616VOLLq2bL._AC_SY355_.jpg          → "616VOLLq2bL"
      .../images/I/616VOLLq2bL._AC_UL348_SR348,348_.jpg → "616VOLLq2bL"
      .../images/I/616VOLLq2bL.jpg                     → "616VOLLq2bL"
    一致しない (Amazon CDN 以外 / 形式変更) → 空文字
    """
    if not url:
        return ""
    m = _AMAZON_IMAGE_BASE_RE.search(url)
    return m.group(1) if m else ""


def clean_amazon_image_url(url: str) -> str:
    """size modifier を除いた高解像度版 URL を返す.

    例: .../I/616VOLLq2bL._AC_SY355_.jpg → https://m.media-amazon.com/images/I/616VOLLq2bL.jpg
    base ID が抽出できない URL はそのまま返す (フォールバック)。
    """
    base = amazon_image_base_id(url)
    if base:
        return f"https://m.media-amazon.com/images/I/{base}.jpg"
    return url


def dedupe_amazon_images(raw_urls: list[str]) -> list[str]:
    """Amazon 画像 URL リストを base ID で dedupe + 高解像度版 URL に正規化.

    入力: サイズ違い・サムネイル混在の URL 群
    出力: 商品画像ごとに 1 つの高解像度版 URL (順序は入力の最初の出現順)
    """
    seen_bases: set[str] = set()
    seen_urls: set[str] = set()  # base が抽出できないケースの fallback dedupe
    result: list[str] = []
    for u in raw_urls:
        if not u:
            continue
        base = amazon_image_base_id(u)
        if base:
            if base in seen_bases:
                continue
            seen_bases.add(base)
            result.append(clean_amazon_image_url(u))
        else:
            # Amazon CDN パターン外: URL そのまま (重複だけ排除)
            if u in seen_urls:
                continue
            seen_urls.add(u)
            result.append(u)
    return result


def _extract_image_urls(driver) -> list[str]:
    """商品の代表画像を 1 枚だけ取得 (高解像度版に正規化).

    収集ソース:
      1) #imageBlock_feature_div の data-a-dynamic-image (JSON map) の最初の URL
      2) フォールバック: #landingImage の src/data-old-hires
    最終出力: メイン画像 1 URL のみのリスト (見つからなければ空配列)。

    複数画像は eBay 出品時に listing スクリプトが Amazon を再訪問して
    取得する想定 (harvest では代表画像のみ保持)。
    """
    from selenium.webdriver.common.by import By  # noqa: PLC0415

    raw_urls: list[str] = []

    # 1) data-a-dynamic-image: メイン画像が最初に来る JSON map
    try:
        elements = driver.find_elements(By.CSS_SELECTOR, "img[data-a-dynamic-image]")
        for el in elements:
            try:
                json_str = el.get_attribute("data-a-dynamic-image") or ""
            except Exception:
                json_str = ""
            if not json_str:
                continue
            for m in re.finditer(r'"(https?://[^"]+)"', json_str):
                raw_urls.append(m.group(1))
                break  # 各 img の最初の URL のみ
            if raw_urls:
                break
    except Exception:
        pass

    # 2) フォールバック: #landingImage の src/data-old-hires
    if not raw_urls:
        try:
            landing = driver.find_element(By.CSS_SELECTOR, LANDING_IMAGE_SELECTOR)
            for attr in ("data-old-hires", "src"):
                try:
                    u = (landing.get_attribute(attr) or "").strip()
                except Exception:
                    u = ""
                if u:
                    raw_urls.append(u)
                    break
        except Exception:
            pass

    deduped = dedupe_amazon_images(raw_urls)
    return deduped[:1]


def _judge_stock(driver) -> tuple[Optional[bool], str]:
    """在庫判定. (in_stock, status) を返す.

    判定ロジック:
      1) #availability text に在庫切れキーワード → (False, "OUT_OF_STOCK")
      2) #add-to-cart-button が存在 (clickable) → (True, "ON_SALE")
      3) どちらも該当しない → (None, "UNKNOWN")
    """
    from selenium.webdriver.common.by import By  # noqa: PLC0415

    # 1) availability text を確認
    try:
        elem = driver.find_element(By.CSS_SELECTOR, AVAILABILITY_SELECTOR)
        avail_text = (elem.text or "").strip()
    except Exception:
        avail_text = ""

    if avail_text and any(kw in avail_text for kw in UNAVAILABLE_KEYWORDS):
        return False, "OUT_OF_STOCK"

    # 2) add-to-cart-button があれば購入可
    try:
        driver.find_element(By.CSS_SELECTOR, ADD_TO_CART_SELECTOR)
        return True, "ON_SALE"
    except Exception:
        pass

    # 3) buy-now-button のみあるパターン (Amazon Prime 系)
    try:
        driver.find_element(By.CSS_SELECTOR, BUY_NOW_SELECTOR)
        return True, "ON_SALE"
    except Exception:
        pass

    return None, "UNKNOWN"


# ============================================================================
# CLI (動作確認用)
# ============================================================================
if __name__ == "__main__":
    import json
    import sys

    from scrapers.amazon_wishlist import create_driver

    test_url = sys.argv[1] if len(sys.argv) > 1 else (
        "https://www.amazon.co.jp/dp/B08N5WRWNW"
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
    info_disp = dict(info)
    info_disp["description"] = (info_disp["description"] or "")[:120]
    info_disp["image_urls"] = info_disp["image_urls"][:3]
    print(json.dumps(info_disp, ensure_ascii=False, indent=2))
