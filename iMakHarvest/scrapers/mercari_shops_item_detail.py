"""mercari_shops_item_detail - Mercari Shops 商品詳細取得.

通常 Mercari の `mercari_item_detail` から **共通関数 (`_extract_title`,
`_extract_price`, `_extract_condition`, `_extract_description`)** を
import して流用、Shops 専用部分 (在庫判定 / 画像取得 / 色判定) のみ独自実装。

通常 Mercari `mercari_item_detail.py` は **一切 touch しない** (Mercari 安定運用維持)。

【DOM 差分まとめ (2026-05-06 確認)】
| 項目 | 通常 Mercari | Shops |
|---|---|---|
| condition | data-testid="商品の状態" | 同じ ✓ |
| description | data-testid="description" | 同じ ✓ |
| title | data-testid="name" | data-testid="display-name" (TITLE_TESTID_CANDIDATES の fallback で hit) |
| price | data-testid="price" | data-testid="product-price" (PRICE_TESTID_CANDIDATES の fallback で hit) |
| 在庫判定 | checkout-button-container | variant-purchase-button (Shops 専用、本ファイルで実装) |
| 画像 | .slick-list/item-image (static.mercdn.net) | image-0..N (assets.mercari-shops-static.com) |
| size | data-testid="サイズ" | **存在せず** (常に空文字) |
"""
from __future__ import annotations

import time
from typing import Optional

# 通常 Mercari と共通の関数を import 流用 (mercari_item_detail.py は touch なし)
from scrapers.mercari_item_detail import (  # noqa: F401
    DELETION_KEYWORDS,
    _extract_condition,
    _extract_description,
    _extract_price,
    _extract_title,
)


# ============================================================================
# Shops 専用 selector / 定数
# ============================================================================
# title testid (= ハイドレーション 完了 検出に最も安定。 旧 variant-purchase-button
# は 5/26 DOM 変更で testid 属性が削除されたため使用不可)
SHOPS_TITLE_TESTID_SELECTOR = '[data-testid="display-name"]'

# 「購入手続きへ」 button (= 在庫判定用、 testid 属性 無し → text で XPath 探索)
SHOPS_PURCHASE_BUTTON_XPATH = "//button[contains(text(), '購入手続き')]"

# 旧 互換 (= 5/6 まで存在した testid、 5/26 削除確認、 fallback として保持)
SHOPS_PURCHASE_BUTTON_SELECTOR = '[data-testid="variant-purchase-button"]'

# 商品画像 testid: image-0, image-1, ... 連番 (DOM 確認では image-0..image-8)
SHOPS_IMAGE_TESTID_PREFIX = "image-"
SHOPS_IMAGE_MAX_INDEX = 20  # 上限 (実際は ~8 枚程度、安全マージン)

# Shops 商品画像の CDN host (assets.mercari-shops-static.com)
SHOPS_PRODUCT_IMAGE_HOST = "assets.mercari-shops-static.com"

# 売切れ / 取扱中止判定 (Shops の body text)
SHOPS_OUT_OF_STOCK_KEYWORDS = (
    "売り切れ",
    "在庫切れ",
    "在庫がありません",
    "Sold Out",
    "Out of Stock",
)

DETAIL_WAIT_SEC = 20
DETAIL_POLL_INTERVAL = 0.5


def fetch_detail(driver, url: str) -> Optional[dict]:
    """Shops 商品 URL を開いて詳細取得.

    Returns:
        dict (title/price_jpy/condition/description/image_urls/in_stock/status/size/color)
        または None (DOM 解析不能 / page load 失敗)。

        size は常に空文字 (Shops に構造化サイズフィールド無し)。
        color は通常 Mercari と同じ Step 1 (whitelist) → Step 2 (Vision AI) で判定。
        TCG カード等 (extraction_filter で skip 判定) は color/size 両方空文字。
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

    # ハイドレーション待ち: display-name (= title testid) 出現 or 削除キーワード
    # (= 旧 variant-purchase-button は 5/26 DOM 変更で testid 削除、 display-name は安定)
    title_found = False
    deleted = False
    end_at = time.time() + DETAIL_WAIT_SEC
    while time.time() < end_at:
        try:
            driver.find_element(By.CSS_SELECTOR, SHOPS_TITLE_TESTID_SELECTOR)
            title_found = True
            break
        except NoSuchElementException:
            pass
        # 旧 testid fallback (= 互換維持、 もし戻ったら hit する)
        try:
            driver.find_element(By.CSS_SELECTOR, SHOPS_PURCHASE_BUTTON_SELECTOR)
            title_found = True
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
            "size": "",
            "color": "",
        }
    if not title_found:
        return None

    # 在庫判定:
    #   - 売切れキーワード (= "売り切れ" / "在庫切れ" 等) があれば False
    #   - 「購入手続きへ」 button (XPath text 探索) があれば True
    #   - どちらも無ければ True (= search?in_stock=true で絞り済前提、 安全側 True)
    try:
        body_text = driver.find_element(By.TAG_NAME, "body").text or ""
    except Exception:
        body_text = ""
    is_out_of_stock = any(kw in body_text for kw in SHOPS_OUT_OF_STOCK_KEYWORDS)
    if is_out_of_stock:
        in_stock = False
    else:
        try:
            driver.find_element(By.XPATH, SHOPS_PURCHASE_BUTTON_XPATH)
            in_stock = True
        except NoSuchElementException:
            # button text 探索失敗、 売切れ text もなし → 安全側 True
            # (= mercari-shops.com search?in_stock=true で絞り済、 詳細 page 表示できてるなら現役)
            in_stock = True
    status = "ON_SALE" if in_stock else "SOLD_OUT"

    # 通常 Mercari と共通の field 抽出 (testid fallback により Shops でも動作)
    title = _extract_title(driver)
    price_jpy = _extract_price(driver)
    condition = _extract_condition(driver)
    description = _extract_description(driver)

    # Shops 専用画像取得
    image_urls = _extract_shops_image_urls(driver)

    # 色/サイズ抽出: TCG 等 skip 対象は両方空文字 (extraction_filter で判定)
    from scrapers.extraction_filter import should_skip_color_size  # noqa: PLC0415
    if should_skip_color_size(title, description):
        size = ""
        color = ""
    else:
        size = ""  # Shops に構造化サイズ field 無いため常に空文字
        color = _judge_shops_color(image_urls, title=title, description=description)

    return {
        "title": title,
        "price_jpy": price_jpy,
        "condition": condition,
        "description": description,
        "image_urls": image_urls,
        "in_stock": in_stock,
        "status": status,
        "size": size,
        "color": color,
    }


# ============================================================================
# Shops 専用画像取得
# ============================================================================
def _extract_shops_image_urls(driver) -> list[str]:
    """Shops 商品ページから商品画像 URL リストを取得.

    優先順:
      1. data-testid="image-0", "image-1", ... 連番 testid (DOM 確認結果)
      2. フォールバック: img[src*='assets.mercari-shops-static.com'] で URL 直接抽出
    """
    from selenium.webdriver.common.by import By  # noqa: PLC0415

    urls: list[str] = []
    seen: set[str] = set()

    # 1) image-N testid を順に試す
    for i in range(SHOPS_IMAGE_MAX_INDEX):
        testid = f"{SHOPS_IMAGE_TESTID_PREFIX}{i}"
        try:
            elem = driver.find_element(By.CSS_SELECTOR, f'[data-testid="{testid}"]')
        except Exception:
            # image-N が見つからない = 次以降も無いとみなして終了 (連番想定)
            break
        # elem 自体が img の場合と、子に img を持つ場合の両対応
        src = ""
        try:
            tag = (elem.tag_name or "").lower()
            if tag == "img":
                src = elem.get_attribute("src") or elem.get_attribute("data-src") or ""
            else:
                for img in elem.find_elements(By.TAG_NAME, "img"):
                    src = img.get_attribute("src") or img.get_attribute("data-src") or ""
                    if src:
                        break
        except Exception:
            src = ""
        src = (src or "").strip()
        if not src or src in seen:
            continue
        seen.add(src)
        urls.append(src)

    if urls:
        return urls

    # 2) フォールバック: assets.mercari-shops-static.com host で URL 直接抽出
    try:
        imgs = driver.find_elements(
            By.CSS_SELECTOR, f"img[src*='{SHOPS_PRODUCT_IMAGE_HOST}']"
        )
        for img in imgs:
            try:
                src = (img.get_attribute("src") or "").strip()
            except Exception:
                src = ""
            if src and src not in seen:
                seen.add(src)
                urls.append(src)
    except Exception:
        pass

    return urls


# ============================================================================
# Shops 専用色判定 (商品本体画像 URL pattern が通常 Mercari と異なるため)
# ============================================================================
def _first_shops_product_image_url(image_urls: list[str] | None) -> str:
    """Shops 商品本体画像 URL (assets.mercari-shops-static.com host 一致) を返す.

    通常 Mercari の `_first_product_image_url` (`/item/detail/orig/photos/`) とは
    別 host pattern。Shops 画像はそもそも商品画像のみなので、host check は安全策。
    """
    if not image_urls:
        return ""
    for url in image_urls:
        if not url:
            continue
        if SHOPS_PRODUCT_IMAGE_HOST in url:
            return url
    # host check 一致なし → 念のため最初の URL を返す (Shops 画像は通常全部該当する)
    return image_urls[0]


def _judge_shops_color(
    image_urls: list[str] | None,
    title: str = "",
    description: str = "",
) -> str:
    """Shops 商品の色判定 (Step 1 whitelist → Step 2 Vision AI).

    通常 Mercari の `_judge_color` と同等ロジックだが、`_first_product_image_url` の
    URL pattern が Shops と異なるため Shops 専用版を独立実装。
    fail-closed (空文字返却): image_urls 空 / API key 無し / AI 例外 / 漢字出力 等。
    """
    if not image_urls:
        return ""
    product_url = _first_shops_product_image_url(image_urls)
    if not product_url:
        return ""
    try:
        from scrapers.color_vision import (  # noqa: PLC0415
            extract_katakana_color_from_text,
            judge_color_from_image_url,
        )
    except Exception:
        return ""

    # Step 1: title/description から確定的にカタカナ色名抽出 (AI 不要)
    try:
        text_color = extract_katakana_color_from_text(title or "", description or "")
        if text_color:
            return text_color
    except Exception:
        pass

    # Step 2: AI Vision fallback
    try:
        return judge_color_from_image_url(
            product_url, title=title, description=description,
        )
    except Exception:
        return ""


# ============================================================================
# CLI (動作確認用)
# ============================================================================
if __name__ == "__main__":
    import json
    import sys

    from scrapers.mercari_shops_likes import create_driver

    test_url = sys.argv[1] if len(sys.argv) > 1 else (
        "https://jp.mercari.com/shops/product/2JNysv3RcsZP37Dt8Zoaof"
    )
    print(f"--- shops detail: {test_url} ---")
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
