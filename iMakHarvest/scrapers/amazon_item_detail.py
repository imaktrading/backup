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
            "color": "",
            "size": "",
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
            "color": "",
            "size": "",
        }
    if not title_found:
        return None

    title = _extract_title(driver)
    price_jpy = _extract_price(driver)
    description = _extract_description(driver)
    image_urls = _extract_image_urls(driver)
    in_stock, status = _judge_stock(driver)

    # 色/サイズ抽出: TCG 等 skip 対象は両方空文字 (extraction_filter で判定)
    from scrapers.extraction_filter import should_skip_color_size  # noqa: PLC0415
    if should_skip_color_size(title, description):
        color = ""
        size = ""
    else:
        color = _judge_amazon_color(driver, image_urls, title=title, description=description)
        size = _extract_amazon_size(driver)

    return {
        "title": title,
        "price_jpy": price_jpy,
        "condition": "New",  # Amazon ウィッシュリストは新品基準
        "description": description,
        "image_urls": image_urls,
        "in_stock": in_stock,
        "status": status,
        "color": color,
        "size": size,
    }


# ============================================================================
# Amazon 色判定 (3-stage、2026-05-13 Phase 1c-color)
# ============================================================================
# Amazon variant selectors (variant 商品時のみ存在、構造化された出品者表記)
_VARIANT_COLOR_SELECTORS = (
    "#variation_color_name .selection",
    "#variation_color_name span.selection",
    "#inline-twister-expanded-dimension-text-color_name",
)
_VARIANT_SIZE_SELECTORS = (
    "#variation_size_name .selection",
    "#variation_size_name span.selection",
    "#inline-twister-expanded-dimension-text-size_name",
)


def _extract_amazon_variant_color(driver) -> str:
    """Amazon variant selector から現在選択色名を取得.

    Amazon variant 商品 (色違い展開あり) で `#variation_color_name .selection` 等が存在。
    返値は出品者表記そのまま (例: "ネイビー", "ブラック", "Black"). 後段で validation。
    variant なし商品 → 空文字。
    """
    from selenium.webdriver.common.by import By  # noqa: PLC0415

    for sel in _VARIANT_COLOR_SELECTORS:
        try:
            elem = driver.find_element(By.CSS_SELECTOR, sel)
            text = (elem.text or "").strip()
            if text:
                return text
        except Exception:
            continue
    return ""


def _extract_amazon_size(driver) -> str:
    """Amazon variant selector から現在選択サイズを取得.

    variant 商品 (サイズ違い展開あり、衣類・靴等) で取れる。それ以外は空文字。
    """
    from selenium.webdriver.common.by import By  # noqa: PLC0415

    for sel in _VARIANT_SIZE_SELECTORS:
        try:
            elem = driver.find_element(By.CSS_SELECTOR, sel)
            text = (elem.text or "").strip()
            if text:
                return text
        except Exception:
            continue
    return ""


def _judge_amazon_color(
    driver,
    image_urls: list[str] | None,
    title: str = "",
    description: str = "",
) -> str:
    """Amazon 色判定 (3-stage、Precision 100% / fail-closed).

    Step 1: variant selector (#variation_color_name) — 出品者明示の構造化フィールド
            parse_color_response で validation (漢字 reject / 不確実キーワード除外)
    Step 2: title / description から whitelist 一致のカタカナ色名 (Mercari と共通関数)
    Step 3: Claude Haiku Vision で画像 + テキスト判定 (image_urls[0])

    fail-closed: いずれも該当なし or AI 例外 → 空文字 (HQ catalog fallback 委ね)
    """
    # Step 1: variant selector (Amazon 固有)
    try:
        from scrapers.color_vision import parse_color_response  # noqa: PLC0415
        variant_color = _extract_amazon_variant_color(driver)
        if variant_color:
            validated = parse_color_response(variant_color)
            if validated:
                return validated
    except Exception:
        pass

    # Step 2: title / description から確定的にカタカナ色名抽出 (AI 不要、Mercari と共通)
    try:
        from scrapers.color_vision import extract_katakana_color_from_text  # noqa: PLC0415
        text_color = extract_katakana_color_from_text(title or "", description or "")
        if text_color:
            return text_color
    except Exception:
        pass

    # Step 3: Vision AI fallback (image_urls[0] = 商品メイン画像)
    if not image_urls:
        return ""
    try:
        from scrapers.color_vision import judge_color_from_image_url  # noqa: PLC0415
        return judge_color_from_image_url(
            image_urls[0], title=title, description=description,
        )
    except Exception:
        return ""


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
# 拡張版 fetch_detail_full (= 2026-06-11 一石二鳥案 / 6 field 追加)
# ============================================================================
# Catalog Q3 回答 (2026-06-11): 型番は Harvest 側で正規化しない、 生 (verbatim) で記録。
# `model_number` は spec block の生型番、 `product_id_estimated` は title からの参考抽出のみ。

# 販売者 (= seller=Amazon.co.jp) 判別 markers (= 表記揺れに緩く対応)
SELLER_AMAZON_JP_MARKERS = (
    "販売: Amazon.co.jp",
    "販売元: Amazon.co.jp",
    "販売: Amazon",
    "販売元: Amazon",
    "販売・発送：Amazon.co.jp",
    "販売・発送: Amazon",
    "発送元 Amazon.co.jp",
    "発送元: Amazon",
    "Sold by Amazon.co.jp",
    "Sold by Amazon",
    "Ships from Amazon.co.jp",
    "Ships from Amazon",
    "Amazon.co.jp が販売",
    "Amazon.co.jpが販売",
)

# seller 緩い判定 (= Amazon が販売 + 発送 双方 と書かれる: 「販売」 と「発送」 と「Amazon.co.jp」 が
# detail page 内の merchant-info block に同居する強い signal)
SELLER_AMAZON_BLOCK_SELECTORS = (
    "#merchant-info",
    "#merchantInfoFeature_feature_div",
    "#tabular-buybox",
    "#fulfillerInfoFeature_feature_div",
)

# spec block selectors (= 型番 / ブランド / 発売日 を含む)
SPEC_TABLE_SELECTORS = (
    "#productDetails_techSpec_section_1 tr",
    "#productDetails_detailBullets_sections1 tr",
    "#detailBullets_feature_div li",
    "#productDetails_db_sections tr",
)

# 評価
RATING_SELECTORS = (
    "i[data-hook='average-star-rating'] span.a-icon-alt",
    "#acrPopover span.a-icon-alt",
    "#averageCustomerReviews span.a-icon-alt",
)

# review_count
REVIEW_COUNT_SELECTORS = (
    "#acrCustomerReviewText",
    "[data-hook='total-review-count']",
)

# brand
BRAND_SELECTORS = (
    "#bylineInfo",
    "tr.po-brand td.po-break-word span",
)

# title 内 G-shock 型番 regex (= 参考、 推測抽出。 catalog 側 lookup_gshock で正規化される)
GSHOCK_MODEL_IN_TITLE_RE = re.compile(
    r"\b([A-Z]{1,5}-[A-Z0-9]+-[A-Z0-9]+(?:[A-Z]{1,5})?)\b"
)

# Amazon inline twister variant container (= 2026 新 UI)
VARIANT_CONTAINER_SELECTORS = (
    "#inline-twister-row-color_name",
    "#variation_color_name",  # 旧 UI
)
# 各 variant の子 ASIN を持つ li
VARIANT_OPTION_LI_SELECTORS = (
    "#inline-twister-row-color_name li[data-asin]",
    "#variation_color_name li[data-defaultasin]",
)


def extract_variant_asins(driver) -> list[str]:
    """detail page から color variant 全子 ASIN list 取得 (= 順序保持 + dedup).

    新 UI (= inline-twister): li[data-asin] / data-csa-c-item-id
    旧 UI (= variation_color_name): li[data-defaultasin]

    variant が無い (= 単独商品) → 空 list。
    """
    from selenium.webdriver.common.by import By  # noqa: PLC0415

    asins: list[str] = []
    seen: set[str] = set()
    for sel in VARIANT_OPTION_LI_SELECTORS:
        try:
            els = driver.find_elements(By.CSS_SELECTOR, sel)
        except Exception:
            els = []
        for el in els:
            for attr in ("data-asin", "data-csa-c-item-id", "data-defaultasin"):
                try:
                    asin = (el.get_attribute(attr) or "").strip().upper()
                except Exception:
                    asin = ""
                if asin and re.fullmatch(r"[A-Z0-9]{10}", asin) and asin not in seen:
                    seen.add(asin)
                    asins.append(asin)
                    break
        if asins:
            break  # 1 つの selector で取れたら他は試さない (= 重複 li 回避)
    return asins


def extract_variant_count(driver) -> int:
    """variant container の data-totalvariationcount から variant 総数取得.

    取れなければ extract_variant_asins() の len() と一致するはず。
    比較で「li が想定数より少ない (= scroll 必要)」 を検出する用。
    """
    from selenium.webdriver.common.by import By  # noqa: PLC0415

    for sel in (
        "#inline-twister-expander-content-color_name",
        "#twister_feature_div [data-totalvariationcount]",
    ):
        try:
            el = driver.find_element(By.CSS_SELECTOR, sel)
            v = el.get_attribute("data-totalvariationcount") or ""
            if v.isdigit():
                return int(v)
        except Exception:
            continue
    return 0


def _extract_seller(driver) -> str:
    """販売者 / 発送元 を判定 → 「Amazon.co.jp」 / 第三者出品者名 / 空文字.

    判定 cascade:
      1. merchant-info / tabular-buybox block 内 text に Amazon.co.jp marker → "Amazon.co.jp"
      2. body 全文 から marker → "Amazon.co.jp"
      3. #sellerProfileTriggerId text → 第三者出品者名
      4. tabular-buybox の row → Amazon / 第三者
      5. 判定不能 → 空文字 (= 第三者として除外される)
    """
    from selenium.webdriver.common.by import By  # noqa: PLC0415

    # 1) merchant block 内 text に絞って Amazon 判定 (= 高精度)
    for sel in SELLER_AMAZON_BLOCK_SELECTORS:
        try:
            els = driver.find_elements(By.CSS_SELECTOR, sel)
        except Exception:
            els = []
        for el in els:
            try:
                t = (el.text or "").strip()
            except Exception:
                t = ""
            if not t:
                continue
            # block 内に Amazon.co.jp が「販売」「発送」 と紐づいて存在 → 直販
            has_amazon = "Amazon.co.jp" in t or "Amazon" in t
            has_sale_or_ship = any(
                kw in t for kw in ("販売", "発送", "Sold by", "Ships from", "が販売", "が発送")
            )
            if has_amazon and has_sale_or_ship:
                # ただし block 内に第三者出品者名 (= "...が販売") のみで Amazon は発送のみ
                # の場合があるので、 厳密に「Amazon.co.jp が販売」 / 「販売: Amazon」 で確認
                if any(mk in t for mk in SELLER_AMAZON_JP_MARKERS):
                    return "Amazon.co.jp"
                # 「販売元 Amazon.co.jp」 のような line 形 → Amazon
                if (
                    "販売元" in t and "Amazon" in t
                ) or (
                    "Sold by" in t and "Amazon" in t
                ):
                    return "Amazon.co.jp"

    # 2) body 全文 から marker
    try:
        body_text = driver.find_element(By.TAG_NAME, "body").text or ""
    except Exception:
        body_text = ""
    if any(mk in body_text for mk in SELLER_AMAZON_JP_MARKERS):
        return "Amazon.co.jp"

    # 3) merchant link (= #sellerProfileTriggerId text、 第三者は通常ここに名前出る)
    try:
        elem = driver.find_element(By.CSS_SELECTOR, "#sellerProfileTriggerId")
        seller_name = (elem.text or "").strip()
        if seller_name:
            if "Amazon" in seller_name:
                return "Amazon.co.jp"
            return seller_name
    except Exception:
        pass

    # 4) tabular buybox 内 row 走査
    try:
        rows = driver.find_elements(
            By.CSS_SELECTOR, "#tabular-buybox .tabular-buybox-text, "
            "#tabular-buybox-truncated-1 .tabular-buybox-text",
        )
        for el in rows:
            try:
                t = (el.text or "").strip()
            except Exception:
                t = ""
            if not t:
                continue
            if "Amazon" in t:
                return "Amazon.co.jp"
            return t  # 第三者出品者名

    except Exception:
        pass

    return ""


def _extract_spec_pairs(driver) -> dict[str, str]:
    """spec table / detail bullets から key:value 辞書を構築."""
    from selenium.webdriver.common.by import By  # noqa: PLC0415

    pairs: dict[str, str] = {}
    for sel in SPEC_TABLE_SELECTORS:
        try:
            rows = driver.find_elements(By.CSS_SELECTOR, sel)
        except Exception:
            rows = []
        for r in rows:
            try:
                txt = (r.text or "").strip()
            except Exception:
                txt = ""
            if not txt:
                continue
            # tr 形式: 「キー 値」 / li 形式: 「キー : 値」
            # split で 2 要素に分け、 key を normalize (= 余分な空白 / 全角コロン除去)
            if "\n" in txt:
                k, _, v = txt.partition("\n")
            elif ":" in txt:
                k, _, v = txt.partition(":")
            elif "：" in txt:
                k, _, v = txt.partition("：")
            else:
                continue
            k = re.sub(r"\s+", "", k).strip()
            v = v.strip()
            if k and v and k not in pairs:
                pairs[k] = v
    return pairs


def _extract_brand(driver, spec_pairs: dict[str, str]) -> str:
    """ブランド名抽出 (= spec_pairs 優先、 fallback で bylineInfo)."""
    for k in ("ブランド", "ブランド名", "メーカー", "Brand"):
        v = spec_pairs.get(k, "").strip()
        if v:
            return v
    from selenium.webdriver.common.by import By  # noqa: PLC0415

    for sel in BRAND_SELECTORS:
        try:
            elem = driver.find_element(By.CSS_SELECTOR, sel)
            t = (elem.text or "").strip()
        except Exception:
            t = ""
        if not t:
            continue
        # "ブランド: CASIO" のような prefix 除去
        t = re.sub(r"^(ブランド|Brand|Visit the)[\s:：]*", "", t).strip()
        # "の Store" / "ストア" 等 suffix 除去
        t = re.sub(r"(の|を)?(ストア|Store|公式|の販売).*$", "", t).strip()
        if t:
            return t
    return ""


def _extract_model_number(driver, spec_pairs: dict[str, str]) -> str:
    """型番抽出 (= spec_pairs 内 「型番」 / 「メーカー型番」 を verbatim).

    Catalog Q3: Harvest 側で正規化しない、 生のまま record。
    """
    for k in ("型番", "メーカー型番", "ASIN", "ItemModelNumber", "型式", "モデル番号"):
        v = spec_pairs.get(k, "").strip()
        if v and k != "ASIN":
            return v
    return ""


def _extract_release_date_amazon(driver, spec_pairs: dict[str, str]) -> str:
    """Amazon 取扱開始日 / 発売日 (= verbatim)."""
    for k in ("Amazon.co.jpでの取り扱い開始日", "発売日", "取り扱い開始日", "Date First Available"):
        v = spec_pairs.get(k, "").strip()
        if v:
            return v
    return ""


def _extract_review_count(driver) -> Optional[int]:
    """レビュー件数 (= 例 "1,234 件のレビュー" → 1234). 無ければ None."""
    from selenium.webdriver.common.by import By  # noqa: PLC0415

    for sel in REVIEW_COUNT_SELECTORS:
        try:
            elem = driver.find_element(By.CSS_SELECTOR, sel)
            txt = (elem.text or "").strip()
        except Exception:
            txt = ""
        if not txt:
            continue
        m = re.search(r"([\d,]+)", txt)
        if m:
            try:
                return int(m.group(1).replace(",", ""))
            except ValueError:
                continue
    return None


def _extract_rating(driver) -> Optional[float]:
    """星評価 (= 例 "5つ星のうち4.3" → 4.3). 無ければ None.

    "5つ星のうち" を先行 keyword として skip し、 その後の数値を取る。
    """
    from selenium.webdriver.common.by import By  # noqa: PLC0415

    rating_value_patterns = [
        re.compile(r"5つ星のうち\s*([\d.]+)"),
        re.compile(r"out of 5 stars[\s,]*([\d.]+)", re.IGNORECASE),
        re.compile(r"([\d.]+)\s*out of 5", re.IGNORECASE),
    ]
    for sel in RATING_SELECTORS:
        try:
            elem = driver.find_element(By.CSS_SELECTOR, sel)
            txt = (elem.get_attribute("textContent") or elem.text or "").strip()
        except Exception:
            txt = ""
        if not txt:
            continue
        # rating value pattern を優先 (= "5つ星のうち X.X" 形)
        for pat in rating_value_patterns:
            m = pat.search(txt)
            if m:
                try:
                    v = float(m.group(1))
                    if 0.0 <= v <= 5.0:
                        return v
                except ValueError:
                    continue
        # fallback: 単独数値
        m = re.search(r"\b([\d.]+)\b", txt)
        if m:
            try:
                v = float(m.group(1))
                if 0.0 <= v <= 5.0:
                    return v
            except ValueError:
                continue
    return None


def _extract_product_id_estimated_from_title(title: str) -> str:
    """title から G-shock 型番候補を regex 抽出 (= 参考値、 catalog 側で resolve)."""
    if not title:
        return ""
    m = GSHOCK_MODEL_IN_TITLE_RE.search(title.upper())
    return m.group(1) if m else ""


def fetch_detail_full(driver, url: str) -> Optional[dict]:
    """fetch_detail の拡張版 (= 14 field、 Amazon 直販 G-shock catalog 投入用).

    返却 dict は fetch_detail の 9 field + 以下 6 field:
      - seller (str)               : "Amazon.co.jp" / 第三者出品者名 / ""
      - brand (str)                : ブランド名 (= 例 "CASIO")
      - model_number (str)         : spec block 型番 (verbatim、 推測しない)
      - release_date_amazon (str)  : Amazon 取扱開始日 / 発売日
      - review_count (int | None)  : レビュー件数
      - rating (float | None)      : 星評価 (= 0.0-5.0)
      - product_id_estimated (str) : title 内 G-shock 型番 regex (= 参考値)
      - amazon_url (str)           : url (引数そのまま)
    """
    base = fetch_detail(driver, url)
    if base is None:
        return None
    if base.get("status") in ("CAPTCHA", "DELETED"):
        # 中断系は 6 field 抽出 skip、 base + 空の 6 field を返す
        extra = {
            "seller": "",
            "brand": "",
            "model_number": "",
            "release_date_amazon": "",
            "review_count": None,
            "rating": None,
            "product_id_estimated": "",
            "amazon_url": url,
        }
        return {**base, **extra}

    spec_pairs = _extract_spec_pairs(driver)
    variant_asins = extract_variant_asins(driver)
    variant_total = extract_variant_count(driver)
    return {
        **base,
        "seller": _extract_seller(driver),
        "brand": _extract_brand(driver, spec_pairs),
        "model_number": _extract_model_number(driver, spec_pairs),
        "release_date_amazon": _extract_release_date_amazon(driver, spec_pairs),
        "review_count": _extract_review_count(driver),
        "rating": _extract_rating(driver),
        "product_id_estimated": _extract_product_id_estimated_from_title(base.get("title", "")),
        "amazon_url": url,
        "variant_asins": variant_asins,
        "variant_total": variant_total,
    }


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
