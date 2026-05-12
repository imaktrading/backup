"""ebay_listing_scraper - eBay 公開 listing 詳細ページから Title / Price / Qty / Item Specifics を取得.

5/12 seller_hub_relist (再出品ツール) の OLD state 保存用に新設。Trading API は
Revise くん挫折 (Profile 空欄 bug) のため、公開ページ scrape で代替。

依存:
  - undetected_chromedriver (seller_hub_view.py と同 profile を共有)
  - selenium

使い方:
  from ebay_listing_scraper import scrape_listing_detail
  with scrape_session() as drv:
      data = scrape_listing_detail(drv, "https://www.ebay.com/itm/356931967951")
"""
from __future__ import annotations

import re
import time
from contextlib import contextmanager

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException, WebDriverException

# Seller Hub 用 (login 必須、iMakInventory と共有)
EBAY_CHROME_PROFILE_DIR = r"C:\Users\imax2\local_data\iMakInventory\chrome_profile_ebay"
# 公開 listing scrape 用 (login 不要、専用 dir → JP 翻訳が account 設定で
# 強制されないよう未ログイン状態を維持)
PUBLIC_SCRAPE_PROFILE_DIR = r"C:\Users\imax2\local_data\iMakHQ\chrome_profile_ebay_public"


@contextmanager
def scrape_session(headless: bool = False, use_login_profile: bool = False):
    """eBay listing detail 公開 scrape 用 Selenium session.

    use_login_profile=False (default): 専用未ログイン profile → eBay の翻訳が
        account 設定 (JP) に引きずられず、原文 (英語) で Title 取得できる。
    use_login_profile=True: iMakInventory 共有 profile (seller_hub_view 等)。
        Seller Hub のような login 必要なページ用、listing detail scrape では非推奨。

    headless=True: 顔出さず実行 (検証完了後の本番向け)。
    """
    profile_dir = (EBAY_CHROME_PROFILE_DIR if use_login_profile
                   else PUBLIC_SCRAPE_PROFILE_DIR)
    options = uc.ChromeOptions()
    options.add_argument(f"--user-data-dir={profile_dir}")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--lang=en-US")
    options.add_argument("--accept-lang=en-US,en;q=0.9")
    if headless:
        options.add_argument("--headless=new")
    drv = uc.Chrome(options=options)
    # CDP で Accept-Language ヘッダーを強制上書き
    try:
        drv.execute_cdp_cmd("Network.enable", {})
        drv.execute_cdp_cmd("Network.setExtraHTTPHeaders", {
            "headers": {"Accept-Language": "en-US,en;q=0.9"}
        })
    except Exception:
        pass
    try:
        yield drv
    finally:
        try:
            drv.quit()
        except Exception:
            pass


_ITEM_ID_RE = re.compile(r"/itm/(?:[^/]+/)?(\d{10,15})")


def normalize_listing_url(url_or_id: str) -> str:
    """URL or ItemID を eBay 公開 listing URL (英語強制) に正規化.

    `?_culture=en-US` パラメータで eBay UI 言語を URL 単位で英語固定。
    """
    if url_or_id.isdigit():
        url = f"https://www.ebay.com/itm/{url_or_id}"
    else:
        url = url_or_id
    # culture param 追加 (既存 query があれば & で連結)
    if "_culture=" not in url:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}_culture=en-US"
    return url


def _safe_text(elem) -> str:
    try:
        return (elem.text or "").strip()
    except Exception:
        return ""


def _find_first(driver, selectors: list[tuple[str, str]]):
    """複数 selector を fallback 試行、最初に取れた element を返す."""
    for by, sel in selectors:
        try:
            elems = driver.find_elements(by, sel)
            if elems:
                return elems[0]
        except Exception:
            continue
    return None


def _extract_title(driver) -> str:
    elem = _find_first(driver, [
        (By.CSS_SELECTOR, "h1.x-item-title__mainTitle span"),
        (By.CSS_SELECTOR, "h1.x-item-title__mainTitle"),
        (By.CSS_SELECTOR, ".x-item-title h1"),
        (By.CSS_SELECTOR, "h1[itemprop='name']"),
        (By.CSS_SELECTOR, "h1"),
    ])
    if not elem:
        return ""
    txt = _safe_text(elem)
    # 接頭詞除去
    for prefix in ("Details about", "Details about ", "Be the first to write a review."):
        if txt.startswith(prefix):
            txt = txt[len(prefix):].strip()
    return txt


def _extract_price(driver) -> tuple[str, str]:
    """(price_usd, price_raw) を返す."""
    elem = _find_first(driver, [
        (By.CSS_SELECTOR, "[data-testid='x-bin-price'] .ux-textspans"),
        (By.CSS_SELECTOR, ".x-price-primary .ux-textspans"),
        (By.CSS_SELECTOR, ".x-price-primary"),
        (By.CSS_SELECTOR, "[itemprop='price']"),
    ])
    raw = _safe_text(elem) if elem else ""
    m = re.search(r"US\s*\$([0-9,.]+)", raw)
    usd = m.group(1).replace(",", "") if m else ""
    return usd, raw


def _extract_quantity(driver) -> str:
    """Available quantity (在庫数)."""
    elem = _find_first(driver, [
        (By.CSS_SELECTOR, "[data-testid='x-quantity'] .ux-textspans"),
        (By.CSS_SELECTOR, ".x-quantity__availability .ux-textspans"),
    ])
    txt = _safe_text(elem) if elem else ""
    m = re.search(r"(\d+)", txt)
    return m.group(1) if m else ""


def _extract_item_specifics(driver) -> dict[str, str]:
    """Item Specifics (左パネルの key-value 群) を dict で返す."""
    specs: dict[str, str] = {}

    # 新 layout: dl.ux-labels-values--inline 構造
    try:
        rows = driver.find_elements(By.CSS_SELECTOR, "dl.ux-labels-values--inline")
        for row in rows:
            try:
                key_el = row.find_element(By.CSS_SELECTOR, "dt .ux-labels-values__labels-content, dt")
                val_el = row.find_element(By.CSS_SELECTOR, "dd .ux-labels-values__values-content, dd")
                k = _safe_text(key_el)
                v = _safe_text(val_el)
                if k and v:
                    specs[k] = v
            except Exception:
                continue
    except Exception:
        pass

    # 旧 layout (一部カテゴリで残存): tr.attrLabels
    if not specs:
        try:
            rows = driver.find_elements(By.CSS_SELECTOR, "div.itemAttr table tr")
            for row in rows:
                cells = row.find_elements(By.CSS_SELECTOR, "td")
                # td が key-value-key-value の構造で並ぶ
                for i in range(0, len(cells) - 1, 2):
                    k = _safe_text(cells[i]).rstrip(":")
                    v = _safe_text(cells[i + 1])
                    if k and v:
                        specs[k] = v
        except Exception:
            pass

    return specs


def _extract_condition(driver) -> str:
    elem = _find_first(driver, [
        (By.CSS_SELECTOR, "[data-testid='ux-textual-display'] .ux-textspans"),
        (By.CSS_SELECTOR, ".x-item-condition-text .ux-textspans"),
        (By.CSS_SELECTOR, ".condText"),
    ])
    return _safe_text(elem) if elem else ""


def _extract_seller_status(driver) -> str:
    """listing が Active か Ended か判定 (Ended なら "This listing has ended." 等が表示)."""
    page_text = driver.find_element(By.TAG_NAME, "body").text or ""
    if "This listing has ended" in page_text or "This listing was ended" in page_text:
        return "ended"
    if "Sold for" in page_text and "ended" in page_text.lower():
        return "ended"
    return "active"


def scrape_listing_detail(driver, url_or_id: str, wait_seconds: int = 5) -> dict:
    """1 listing の詳細を scrape して dict で返す.

    Returns:
        {
            "url": ..., "item_id": ..., "status": "active"|"ended"|"unknown",
            "title": ..., "price_usd": ..., "price_raw": ..., "quantity": ...,
            "condition": ..., "specifics": {key: value, ...},
            "scrape_error": "" or "<reason>",
        }
    """
    url = normalize_listing_url(url_or_id)
    out = {
        "url": url, "item_id": "", "status": "unknown",
        "title": "", "price_usd": "", "price_raw": "",
        "quantity": "", "condition": "", "specifics": {},
        "scrape_error": "",
    }
    m = _ITEM_ID_RE.search(url)
    if m:
        out["item_id"] = m.group(1)

    try:
        driver.get(url)
        time.sleep(wait_seconds)
    except WebDriverException as e:
        out["scrape_error"] = f"navigate failed: {e}"
        return out

    try:
        out["title"] = _extract_title(driver)
        out["price_usd"], out["price_raw"] = _extract_price(driver)
        out["quantity"] = _extract_quantity(driver)
        out["condition"] = _extract_condition(driver)
        out["specifics"] = _extract_item_specifics(driver)
        out["status"] = _extract_seller_status(driver)
    except Exception as e:
        out["scrape_error"] = f"parse failed: {e}"

    return out


def scrape_listings_batch(urls: list[str], wait_seconds: int = 5,
                          headless: bool = False, progress_callback=None) -> list[dict]:
    """複数 URL を batch scrape (1 session で連続処理).

    progress_callback: 各 listing 完了時に callback(idx, total, result) で呼ばれる
    """
    results: list[dict] = []
    with scrape_session(headless=headless) as drv:
        total = len(urls)
        for i, u in enumerate(urls, start=1):
            r = scrape_listing_detail(drv, u, wait_seconds=wait_seconds)
            results.append(r)
            if progress_callback:
                try:
                    progress_callback(i, total, r)
                except Exception:
                    pass
    return results


if __name__ == "__main__":
    # 単独実行: 引数 URL を 1 件 scrape して dict 表示
    import json
    import sys
    if len(sys.argv) < 2:
        print("Usage: python ebay_listing_scraper.py <url_or_item_id>")
        sys.exit(1)
    with scrape_session() as drv:
        r = scrape_listing_detail(drv, sys.argv[1])
    print(json.dumps(r, ensure_ascii=False, indent=2))
