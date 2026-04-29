"""mercari_scraper - メルカリ / メルカリShops 商品ページの在庫スクレイパー (Selenium ベース).

設計原則:
  - Selenium (undetected_chromedriver) + iMakMercari Chrome プロファイル流用 (ログイン状態継承)
  - メルカリは 2026 年に App Router 移行済 (= 静的 HTML には在庫情報なし、
    requests + __NEXT_DATA__ 方式は使えない)
  - 公開 API は DPoP token 必須 → 直接叩けない
  - 結論: ヘッドレス Chrome で実描画後の DOM を見るのが唯一の方式

在庫判定基準 (DOM testid):
  - 通常 item (/item/m\\d+):
    `[data-testid="checkout-button"]` 存在 → 在庫あり
  - Mercari Shops (/shops/product/<id>):
    `[data-testid="variant-purchase-button"]` 存在 → 在庫あり
  - いずれも存在しない (timeout) → 在庫切れ判定

404 / ページ削除:
  - 高速 path: requests で先に 404 確認 (Selenium 起動より速い)
  - 404 → status="DELETED", in_stock=False

driver 再利用:
  - ループ内で 1 driver を共有してオーバーヘッド削減 (Phase 2 monitor_listings 経由)
  - 単発呼出時は内部で driver を生成・破棄

返却形式 (uniqlo_scraper.fetch_product_inventory と契約互換):
  {
    "name":         商品名,
    "product_id":   メルカリ item id (m\\d+) または "s_<shops_id>",
    "color":        "",
    "status":       "ON_SALE" / "SOLD_OUT" / "DELETED" / "UNKNOWN",
    "fetched_at":   ISO timestamp,
    "skus": [{"size": "", "in_stock": bool, "quantity": 1 or 0, "price_jpy": int or None}]
  }
"""
from __future__ import annotations

import os
import re
import time
from datetime import datetime
from typing import Optional

import requests


# ============================================================================
# 設定
# ============================================================================
MERCARI_ITEM_RE = re.compile(r"/items?/(m\d+)")
MERCARI_SHOPS_RE = re.compile(r"/shops/product/([\w-]+)")
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)
DEFAULT_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept-Language": "ja,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
TIMEOUT_404_CHECK_SEC = 10
SELENIUM_WAIT_SEC = 12     # ハイドレーション完了待ちの最大秒数
SELENIUM_POLL_INTERVAL = 0.5

CHROME_PROFILE_DIR = r"C:\Users\imax2\local_data\iMakMercari\chrome_profile"
CHROME_VERSION_MAIN = 146


# ============================================================================
# URL → item id
# ============================================================================
def parse_item_id(url: str) -> Optional[str]:
    """メルカリ商品 URL から item id を抽出.
    対応:
      - /item/m12345  (regular)
      - /items/m12345 (alt)
      - /shops/product/<random_id>  (Mercari Shops、prefix `s_` 付与)
    """
    if not url:
        return None
    m = MERCARI_ITEM_RE.search(url)
    if m:
        return m.group(1)
    m = MERCARI_SHOPS_RE.search(url)
    if m:
        return f"s_{m.group(1)}"
    return None


def is_mercari_shops_url(url: str) -> bool:
    return bool(url and MERCARI_SHOPS_RE.search(url))


# ============================================================================
# Fast path: 404 detection via requests (Selenium 起動より速い)
# ============================================================================
def _check_404(url: str) -> Optional[bool]:
    """requests で URL を取得し、404 のみ判定.
    Returns:
        True   : 404 確定 (= 削除済 = sold out 扱い)
        False  : 200 OK (= Selenium で詳細判定すべき)
        None   : ネットワークエラー (呼出側で判断)
    """
    try:
        # HEAD 不可な場合があるので GET (但し allow_redirects=True で /not-found に転送される)
        resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=TIMEOUT_404_CHECK_SEC,
                            allow_redirects=False)
        if resp.status_code == 404:
            return True
        if 300 <= resp.status_code < 400:
            # リダイレクト先を確認 (sold/deleted 商品は /list?... 等にリダイレクトされうる)
            loc = resp.headers.get("Location", "")
            if "/not-found" in loc or "/error" in loc:
                return True
        return False
    except requests.RequestException:
        return None


# ============================================================================
# Selenium driver factory
# ============================================================================
def create_driver(headless: bool = True, use_iMakMercari_profile: bool = True):
    """undetected_chromedriver の driver を生成して返す.
    呼出元はループ内で 1 driver を再利用することを推奨。
    """
    try:
        import undetected_chromedriver as uc  # noqa: PLC0415
    except ImportError:
        raise RuntimeError(
            "undetected_chromedriver 未インストール。pip install undetected-chromedriver"
        )

    options = uc.ChromeOptions()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--lang=ja-JP")
    if use_iMakMercari_profile and os.path.isdir(CHROME_PROFILE_DIR):
        options.add_argument(f"--user-data-dir={CHROME_PROFILE_DIR}")
    if headless:
        options.add_argument("--headless=new")

    driver = uc.Chrome(options=options, version_main=CHROME_VERSION_MAIN)
    return driver


# ============================================================================
# Selenium ベース在庫判定
# ============================================================================
def _detect_via_selenium(driver, url: str, is_shops: bool) -> Optional[dict]:
    """driver に url を load し在庫状態を判定.

    Returns:
        {"name", "status", "in_stock", "price_jpy"} or None (判定不能)
    """
    from selenium.webdriver.common.by import By  # noqa: PLC0415
    from selenium.webdriver.support.ui import WebDriverWait  # noqa: PLC0415
    from selenium.webdriver.support import expected_conditions as EC  # noqa: PLC0415
    from selenium.common.exceptions import TimeoutException, WebDriverException  # noqa: PLC0415

    try:
        driver.get(url)
    except WebDriverException:
        return None

    # 在庫あり buy ボタンの testid (URL 種別ごと)
    buy_button_testid = (
        "variant-purchase-button" if is_shops else "checkout-button"
    )

    # ハイドレーション完了 = item-name (item ページ) or display-name (shops) が描画済
    name_testid_candidates = ["item-name", "display-name", "name"]

    # 売切判定基準 (2026-04-29 false-negative バグ修正で導入):
    # checkout-button は売切ページでも DOM に残るため、ボタン要素を見つけた後
    # 以下のいずれかで売切と判定する。
    #   1. button text == "売り切れました"
    #   2. class に "disabled" を含む (merButton の disabled スタイル)
    #   3. name 属性 == "disabled"
    # それ以外 (text="購入手続きへ" 等) は在庫あり判定。
    SOLD_BUTTON_TEXTS = ("売り切れました", "売り切れ", "Sold")

    def _is_sold_button(elem) -> Optional[bool]:
        """buy ボタン要素を見て sold/in_stock/unknown を返す.
        Returns: True=sold, False=in_stock, None=判定不能
        """
        try:
            txt = (elem.text or "").strip()
            cls = (elem.get_attribute("class") or "").lower()
            name_attr = (elem.get_attribute("name") or "").lower()
            disabled_attr = (elem.get_attribute("disabled") or "")
            if txt in SOLD_BUTTON_TEXTS:
                return True
            if "disabled" in cls or name_attr == "disabled" or disabled_attr:
                return True
            # 在庫あり想定の text
            if any(kw in txt for kw in ("購入手続きへ", "購入手続き", "Buy now", "カートに追加")):
                return False
            # text 取得できない / 未知パターン → 判定不能
            return None
        except Exception:
            return None

    in_stock = None
    name = ""
    price_jpy = None
    button_text = ""
    button_class = ""

    end_at = time.time() + SELENIUM_WAIT_SEC
    while time.time() < end_at:
        # buy ボタンを見つけたら状態判定
        try:
            elem = driver.find_element(By.CSS_SELECTOR, f'[data-testid="{buy_button_testid}"]')
            button_text = (elem.text or "").strip()
            button_class = (elem.get_attribute("class") or "")
            judgement = _is_sold_button(elem)
            if judgement is True:
                in_stock = False
                break
            if judgement is False:
                in_stock = True
                break
            # judgement is None: ハイドレーション途中で text 未確定 → 続けてポーリング
        except Exception:
            pass

        # ページが「商品が見つかりません」「削除されました」等を表示しているか
        try:
            page_text = driver.find_element(By.TAG_NAME, "body").text or ""
            if any(kw in page_text for kw in [
                "商品が見つかりません",
                "削除されました",
                "ページが見つかりません",
                "Not Found",
            ]):
                return {
                    "name": "(deleted)",
                    "status": "DELETED",
                    "in_stock": False,
                    "price_jpy": None,
                }
        except Exception:
            pass

        time.sleep(SELENIUM_POLL_INTERVAL)

    if in_stock is None:
        # buy ボタンが timeout 時間内に判定可能状態にならなかった
        # 最終的に sold-out 文字列がページに表示されているかで決める
        try:
            page_text = driver.find_element(By.TAG_NAME, "body").text or ""
            if any(kw in page_text for kw in ("売り切れました", "Sold")):
                in_stock = False
            else:
                # ハイドレーション失敗等で何も判定できない → fail-closed (None)
                return None
        except Exception:
            return None

    # 商品名・価格抽出
    if not name:
        for tid in name_testid_candidates:
            try:
                elem = driver.find_element(By.CSS_SELECTOR, f'[data-testid="{tid}"]')
                name = elem.text.strip()
                if name:
                    break
            except Exception:
                continue

    # price testid
    for tid in ["price", "product-price", "item-price"]:
        try:
            elem = driver.find_element(By.CSS_SELECTOR, f'[data-testid="{tid}"]')
            txt = elem.text.strip()
            m = re.search(r"([\d,]+)", txt)
            if m:
                try:
                    price_jpy = int(m.group(1).replace(",", ""))
                    break
                except ValueError:
                    pass
        except Exception:
            continue

    return {
        "name": name,
        "status": "ON_SALE" if in_stock else "SOLD_OUT",
        "in_stock": bool(in_stock),
        "price_jpy": price_jpy,
    }


# ============================================================================
# 公開 API
# ============================================================================
def fetch_product_inventory(
    url: str,
    driver=None,
    use_selenium_fallback: bool = True,
) -> Optional[dict]:
    """メルカリ / Shops 商品 URL から在庫・価格情報を取得.

    Args:
        url: メルカリ商品 URL
        driver: 外部から渡された Selenium driver (再利用、推奨)。
                None の場合は内部で生成 (1回呼出ごとに開閉=遅い)
        use_selenium_fallback: driver=None の場合の挙動制御。
                              False で 404 path のみ実行 (Selenium 起動を抑制)

    Returns:
        uniqlo_scraper と契約互換の dict、または None (判定不能時)。
    """
    item_id = parse_item_id(url) or ""
    is_shops = is_mercari_shops_url(url)

    # 1) 高速 404 check
    is_404 = _check_404(url)
    if is_404 is True:
        return {
            "name": "(deleted)",
            "product_id": item_id,
            "color": "",
            "status": "DELETED",
            "fetched_at": datetime.now().isoformat(timespec="seconds"),
            "skus": [{"size": "", "in_stock": False, "quantity": 0, "price_jpy": None}],
        }

    # 2) Selenium で在庫判定
    if driver is not None:
        raw = _detect_via_selenium(driver, url, is_shops)
    elif use_selenium_fallback:
        d = create_driver(headless=True)
        try:
            raw = _detect_via_selenium(d, url, is_shops)
        finally:
            try:
                d.quit()
            except Exception:
                pass
    else:
        return None

    if raw is None:
        return None

    return {
        "name": raw.get("name", ""),
        "product_id": item_id,
        "color": "",
        "status": raw.get("status", "UNKNOWN"),
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
        "skus": [
            {
                "size": "",
                "in_stock": bool(raw.get("in_stock", False)),
                "quantity": 1 if raw.get("in_stock") else 0,
                "price_jpy": raw.get("price_jpy"),
            }
        ],
    }


# ============================================================================
# CLI (動作確認用)
# ============================================================================
if __name__ == "__main__":
    import sys
    test_url = sys.argv[1] if len(sys.argv) > 1 else (
        "https://jp.mercari.com/item/m59277919762"
    )
    print(f"--- メルカリ scrape: {test_url} ---")
    info = fetch_product_inventory(test_url)
    if info is None:
        print("  ⚠️ 判定不能 (None)")
        sys.exit(1)
    print(f"  Name:    {info['name'][:60]}")
    print(f"  ItemID:  {info['product_id']}")
    print(f"  Status:  {info['status']}")
    print(f"  InStock: {info['skus'][0]['in_stock']}")
    print(f"  Price:   ¥{info['skus'][0]['price_jpy']}")
