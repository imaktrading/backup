"""snkrdunk_official - スニダン PSA10 補仕入 URL 抽出 (HTTP API + Selenium).

iMakTCG listing → 既存 PSA10 出品の補仕入 URL を探すための scraper。
Phase 1 (commit GO 2026-05-17) スコープ = **ワンピース TCG OP シリーズのみ** (card_id `OP\\d{2}-\\d{3}`)。

設計原則:
  - HTTP-only API を主軸 (Selenium は必要最小限の page render のみ)
  - 集約 + 個別 used の 2 API:
    - `https://snkrdunk.com/v1/apparels/{model_id}` (productNumber 確認用)
    - `https://snkrdunk.com/v1/apparels/{model_id}/used/{instance_id}` (PSA10 grade + price)
  - 検索 / instance list は Selenium で page render (= public API 未発見、Phase 2 で改善余地)
  - PSA10 only filter (`displayShortConditionTitle == "PSA10"`)
  - status=0 (出品中) のみ採用、それ以外は skip (= 即時除外、Inventory 継続監視は別)
  - 失敗時は raise (caller が retry 判断)、card_id 不一致は skip + ログ

返却形式 (per card):
    {
        "card_id": "OP03-044",
        "model_id": 159278,
        "name_en": "Kaya R [OP03-044] (Standard Battle Trophy)",
        "name_jp": "カヤ R [OP03-044] (スタンダードバトル 優勝記念品)",
        "psa10_urls": [
            "https://snkrdunk.com/apparels/159278/used/45538280",
            ...
        ],
        "psa10_count": 3,
    }
"""
from __future__ import annotations

import os
import re
import time
from typing import Optional

import requests


# card_id 抽出: OP01-001 〜 OP99-999 形式 (本シリーズブースターパック)
OP_CARD_ID_RE = re.compile(r"\b(OP\d{2}-\d{3})\b", re.IGNORECASE)

# SNKRDUNK 個別 used URL pattern (= 補仕入 URL として AC-AG 列に投入)
APPAREL_USED_URL_RE = re.compile(
    r"https?://snkrdunk\.com/apparels/(\d+)/used/(\d+)",
    re.IGNORECASE,
)

# SNKRDUNK base URLs
SNKRDUNK_BASE = "https://snkrdunk.com"
APPAREL_API_TEMPLATE = "https://snkrdunk.com/v1/apparels/{model_id}"
APPAREL_USED_API_TEMPLATE = "https://snkrdunk.com/v1/apparels/{model_id}/used/{instance_id}"
APPAREL_USED_PAGE_TEMPLATE = "https://snkrdunk.com/apparels/{model_id}/used"
SEARCH_PAGE_TEMPLATE = "https://snkrdunk.com/search?keyword={keyword}"

# Selenium profile (snkrdunk 専用、他 supplier と分離)
CHROME_PROFILE_DIR = r"C:\Users\imax2\local_data\iMakHarvest\chrome_profile_snkrdunk"
CHROME_VERSION_MAIN = 148  # Mercari/Amazon と同期

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "ja-JP,ja;q=0.9,en;q=0.8",
}
TIMEOUT_SEC = 15
DEFAULT_RATE_LIMIT_SEC = 1.0
SELENIUM_HYDRATION_WAIT_SEC = 8.0

# PSA10 filter: displayShortConditionTitle 完全一致のみ
PSA10_CONDITION_LABEL = "PSA10"
STATUS_ON_SALE = 0  # apparelUsedItem.status: 0 = 出品中


# ============================================================================
# card_id 抽出
# ============================================================================
def extract_op_card_id(text: str) -> Optional[str]:
    """iMakTCG listing title から OP card_id (例: `OP03-044`) を抽出.

    本実装スコープは OP シリーズのみ。ST / EB / P (プロモ) は Phase 2 以降。
    """
    if not text:
        return None
    m = OP_CARD_ID_RE.search(text)
    return m.group(1).upper() if m else None


# ============================================================================
# HTTP-only API: 集約 + 個別 used
# ============================================================================
def fetch_apparel_aggregate(
    model_id: int,
    session: Optional[requests.Session] = None,
) -> Optional[dict]:
    """`/v1/apparels/{model_id}` で集約情報を取得.

    Returns:
        {"productNumber": "OP03-044", "name": "...", "localizedName": "...", ...}
        または None (404 等)
    """
    sess = session or requests
    url = APPAREL_API_TEMPLATE.format(model_id=model_id)
    try:
        resp = sess.get(url, headers=DEFAULT_HEADERS, timeout=TIMEOUT_SEC)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()
    except (requests.RequestException, ValueError):
        return None


def fetch_apparel_used_instance(
    model_id: int,
    instance_id: int,
    session: Optional[requests.Session] = None,
) -> Optional[dict]:
    """`/v1/apparels/{model_id}/used/{instance_id}` で個別 used item 情報を取得.

    Returns:
        {"price": int, "displayShortConditionTitle": "PSA10", "status": 0, ...}
        または None (404 / parse 失敗)
    """
    sess = session or requests
    url = APPAREL_USED_API_TEMPLATE.format(model_id=model_id, instance_id=instance_id)
    try:
        resp = sess.get(url, headers=DEFAULT_HEADERS, timeout=TIMEOUT_SEC)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data = resp.json()
        return data.get("apparelUsedItem")
    except (requests.RequestException, ValueError):
        return None


def is_psa10_on_sale(used_item: dict) -> bool:
    """個別 used item が PSA10 鑑定済 + 出品中かを判定 (fail-closed、両条件必須)."""
    if not used_item:
        return False
    if used_item.get("status") != STATUS_ON_SALE:
        return False
    if (used_item.get("displayShortConditionTitle") or "").strip() != PSA10_CONDITION_LABEL:
        return False
    return True


def build_apparel_used_url(model_id: int, instance_id: int) -> str:
    """個別 used URL を構築 (補仕入 URL として AC-AG 列に投入される形式)."""
    return f"https://snkrdunk.com/apparels/{model_id}/used/{instance_id}"


# ============================================================================
# Selenium: 検索 / instance list page render
# ============================================================================
def create_driver(headless: bool = False, profile_dir: Optional[str] = None):
    """undetected_chromedriver を起動 (SNKRDUNK 専用 profile)."""
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
        options.add_argument("--window-size=820,640")
        options.add_argument("--window-position=80,80")
    driver = uc.Chrome(options=options, version_main=CHROME_VERSION_MAIN)
    return driver


def search_card_to_model_id(driver, card_id: str) -> Optional[int]:
    """home page の検索 input に card_id を入力 → 検索結果から最初の /apparels/<model_id> 取得.

    SNKRDUNK 検索は CSR SPA のため、URL 直接 GET (`/search?keyword=...`) では結果が
    JS でレンダリングされる前に Selenium が取得してしまう。input UI 操作で結果到達後に
    page_source 取得する必要あり (実機検証 2026-05-17)。

    Returns:
        最初にヒットした model_id (int) または None (= 検索結果なし)

    Note: 検索結果が複数ある場合は **最初の 1 件のみ採用**。Phase 1 では OP card_id が
    完全一致なら 1 model に絞られる前提 (= productNumber 突合で再検証する)。
    """
    from selenium.webdriver.common.by import By  # noqa: PLC0415
    from selenium.webdriver.common.keys import Keys  # noqa: PLC0415

    try:
        driver.get(f"{SNKRDUNK_BASE}/")
    except Exception:
        return None
    # home page hydration 待ち
    time.sleep(SELENIUM_HYDRATION_WAIT_SEC / 2)

    # 検索 input を探す: home / category / search page で共通の input[name*=keyword]
    search_input = None
    for sel in (
        'input[name="keyword"]',
        'input[name*="keyword"]',
        'input[type="search"]',
        'input[placeholder*="検索"]',
    ):
        try:
            search_input = driver.find_element(By.CSS_SELECTOR, sel)
            if search_input:
                break
        except Exception:
            continue
    if not search_input:
        return None

    # 検索 keyword 入力 + Enter submit
    try:
        search_input.clear()
        search_input.send_keys(card_id)
        search_input.send_keys(Keys.RETURN)
    except Exception:
        return None

    # 検索結果 hydration 待ち
    time.sleep(SELENIUM_HYDRATION_WAIT_SEC)

    page_source = driver.page_source or ""
    matches = re.findall(r"/apparels/(\d+)(?:[/?\"#]|$)", page_source)
    if not matches:
        return None
    # 重複除去後、最初の model_id を返す (検索結果トップ採用)
    seen: set[str] = set()
    for m in matches:
        if m in seen:
            continue
        seen.add(m)
        try:
            return int(m)
        except ValueError:
            continue
    return None


def fetch_instance_ids_from_used_page(driver, model_id: int) -> list[int]:
    """`/apparels/<model_id>/used` page を render → /used/<instance_id> 一覧抽出.

    Returns: instance_id list (int)、検出ゼロなら空 list
    """
    url = APPAREL_USED_PAGE_TEMPLATE.format(model_id=model_id)
    try:
        driver.get(url)
    except Exception:
        return []
    time.sleep(SELENIUM_HYDRATION_WAIT_SEC)
    page_source = driver.page_source or ""
    matches = re.findall(
        rf"/apparels/{model_id}/used/(\d+)(?:[/?\"#]|$)",
        page_source,
    )
    seen: set[int] = set()
    result: list[int] = []
    for m in matches:
        try:
            iid = int(m)
        except ValueError:
            continue
        if iid in seen:
            continue
        seen.add(iid)
        result.append(iid)
    return result


# ============================================================================
# 統合フロー: card_id → PSA10 補仕入 URL 一覧 (最大 N 件)
# ============================================================================
def find_psa10_urls_for_card(
    card_id: str,
    driver,
    max_results: int = 5,
    session: Optional[requests.Session] = None,
    rate_limit_sec: float = DEFAULT_RATE_LIMIT_SEC,
) -> dict:
    """card_id (例: OP03-044) → PSA10 出品中の補仕入 URL 一覧を取得.

    Args:
        card_id: OP card_id (`OP\\d{2}-\\d{3}` 形式)
        driver: Selenium driver (検索 + used page render 用)
        max_results: 最大取得件数 (= AC-AG 5 列分なので default 5)
        session: requests.Session (API 呼出再利用、optional)
        rate_limit_sec: 各 API 呼出間の sleep

    Returns:
        {
            "card_id": "OP03-044",
            "model_id": 159278 (or None if 検索失敗),
            "name_en": "...",
            "name_jp": "...",
            "psa10_urls": ["https://snkrdunk.com/apparels/159278/used/...", ...],
            "psa10_count": N,
            "search_failed": bool,
        }
    """
    sess = session or requests.Session()
    result = {
        "card_id": card_id,
        "model_id": None,
        "name_en": "",
        "name_jp": "",
        "psa10_urls": [],
        "psa10_count": 0,
        "search_failed": False,
    }

    # Step 1: card_id でスニダン検索 → model_id 取得
    model_id = search_card_to_model_id(driver, card_id)
    if not model_id:
        result["search_failed"] = True
        return result
    result["model_id"] = model_id

    # Step 2: 集約 API で productNumber 確認 (= 完全一致検証、フェイル時 skip)
    aggregate = fetch_apparel_aggregate(model_id, session=sess)
    if not aggregate:
        result["search_failed"] = True
        return result
    api_product_number = (aggregate.get("productNumber") or "").upper()
    if api_product_number != card_id.upper():
        # 検索結果トップが別 card にマッチしている (= 誤マッチ防止、fail-closed skip)
        result["search_failed"] = True
        return result
    result["name_en"] = aggregate.get("name", "")
    result["name_jp"] = aggregate.get("localizedName", "")

    # Step 3: used page render で instance_id 一覧取得
    instance_ids = fetch_instance_ids_from_used_page(driver, model_id)
    if not instance_ids:
        return result  # PSA10 含む used 出品ゼロ、空リスト返却

    # Step 4: 各 instance を API で fetch、PSA10 + status=0 filter
    psa10_urls: list[str] = []
    for iid in instance_ids:
        if len(psa10_urls) >= max_results:
            break
        used_item = fetch_apparel_used_instance(model_id, iid, session=sess)
        if rate_limit_sec > 0:
            time.sleep(rate_limit_sec)
        if not is_psa10_on_sale(used_item):
            continue
        psa10_urls.append(build_apparel_used_url(model_id, iid))

    result["psa10_urls"] = psa10_urls
    result["psa10_count"] = len(psa10_urls)
    return result


# ============================================================================
# CLI (動作確認用)
# ============================================================================
if __name__ == "__main__":
    import argparse
    import json
    import sys

    ap = argparse.ArgumentParser()
    ap.add_argument(
        "card_id",
        nargs="?",
        default="OP03-044",
        help="OP card_id (例: OP03-044)",
    )
    ap.add_argument(
        "--max-results", type=int, default=5, help="最大取得件数 (AC-AG 5 列分)"
    )
    args = ap.parse_args()

    print(f"--- snkrdunk PSA10 検索: {args.card_id} ---")
    driver = create_driver(headless=False)
    try:
        info = find_psa10_urls_for_card(args.card_id, driver, max_results=args.max_results)
    finally:
        try:
            driver.quit()
        except Exception:
            pass
    print(json.dumps(info, ensure_ascii=False, indent=2))
    if info["psa10_count"] == 0:
        print("⚠️ PSA10 出品なし or 検索失敗")
        sys.exit(1)
