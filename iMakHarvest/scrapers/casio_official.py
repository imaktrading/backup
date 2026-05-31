"""casio_official - Casio 公式 (= casio.com/jp/watches/gshock) G-shock series scrape.

iMakHarvest 配下の新規 scraper。 Catalog Claude 依頼 (2026-05-31) で
G-shock catalog 拡張用に Casio 公式から全 SUBSERIES の variant 一覧 + 詳細 を
JSON dump する。

【抽出くん流 anti-detection】(= mercari_seller.py 5/26 release ノウハウ流用):
- undetected_chromedriver (= mercari_likes.create_driver、 version_main=148)
- 永続 chrome profile (= 完全分離: chrome_profile_casio_anon)
- jitter sleep (= random.uniform(2.0, 4.0) 秒、 詳細取得間)
- adaptive backoff (= 429 検出時 5s → 10s → 20s)
- initial wait 18s (= 初期 hydration)
- Akamai 系 bot 検出 回避 (= UCD default UA + chrome 本体 fingerprint)

【scope】(= 5/31 依頼書 sec 3-1):
- 入力: SUBSERIES list (= ShockBase の 228 件 想定、 ただし URL pattern は要確認)
- 出力: C:/dev/iMak_data/catalog/_casio_official_dumps/series_<TYPE>_<ts>.json
- 形式: ShockBase batch dump と同 schema

【未確定 / 判断要】(= 5/31 POC で判明):
- URL pattern は ShockBase SUBSERIES と直結しない (= 例: MTG-B1000 → /type/mt-g/ は 404)
- Casio TYPE 粒度 (= 5600 / 6900) > ShockBase SUBSERIES 粒度 (= GW-M5610 / GD-X6900)
- 全 type の自動 discovery が本実装の前提 (= 別 phase で起票予定)
"""
from __future__ import annotations

import json
import os
import random
import re
import time
from datetime import datetime
from typing import Callable, Optional

from selenium.webdriver.common.by import By

from scrapers import mercari_likes

# ============================================================================
# Constants
# ============================================================================
# Casio 公式 series page URL pattern (= /jp/watches/gshock/products/type/<TYPE>/all/)
CASIO_SERIES_URL_TEMPLATE = (
    "https://www.casio.com/jp/watches/gshock/products/type/{type_slug}/all/"
)

# Casio 公式 product (= variant) URL pattern (= /jp/watches/gshock/product.<MODEL>/)
CASIO_PRODUCT_URL_RE = re.compile(
    r"casio\.com/jp/watches/gshock/product\.([A-Z0-9\-]+)/?",
    re.IGNORECASE,
)

# 抽出くん流 永続 chrome profile (= casio 専用 anonymous、 完全分離)
CHROME_PROFILE_DIR_CASIO = (
    r"C:\Users\imax2\local_data\iMakHarvest\chrome_profile_casio_anon"
)

# rate limit (= mercari_seller と同値、 詳細取得間 sleep)
DEFAULT_REQUEST_RATE_LIMIT_MIN_SEC = 2.0
DEFAULT_REQUEST_RATE_LIMIT_MAX_SEC = 4.0

# initial hydration (= mercari_seller と同値)
DEFAULT_INITIAL_WAIT_SEC = 18

# adaptive backoff (= 429 / blocked 検出時、 倍々で escalate)
DEFAULT_BACKOFF_SCHEDULE_SEC = (5.0, 10.0, 20.0)

# bot 検出 / 429 判定 marker (= body innerText で検出)
BLOCKED_MARKERS = (
    "access denied", "429", "blocked", "too many", "captcha",
    "rate limit", "forbidden",
)
# 404 判定 (= title or body)
NOT_FOUND_MARKERS = (
    "404", "お探しのページは見つかりませんでした",
)
# chrome side protocol / connection error 検出 (= 6/1 MR-G 29 件 で頻発)
CHROME_ERROR_MARKERS = (
    "このサイトにアクセスできません",
    "err_http",
    "err_connection",
    "err_name_not_resolved",
    "this site can't be reached",
    "this webpage is not available",
)

# 出力先 (= 依頼書 sec 3-2)
DUMP_DIR = r"C:\dev\iMak_data\catalog\_casio_official_dumps"

# all-linup page (= 5/31 Option A discovery で判明、 G-shock 全 variant URL 集約 page)
ALL_LINUP_URL = "https://gshock.casio.com/jp/products/all-linup/"

# variant URL pattern (= www.casio.com/jp/watches/gshock/product.<MODEL>/ を all-linup から抽出)
# all-linup 内に直接 product.MODEL/ link が含まれる
ALL_LINUP_SCROLL_INTERVAL_SEC = 2.5
ALL_LINUP_NO_PROGRESS_THRESHOLD = 3
ALL_LINUP_MAX_SCROLLS = 40


# ============================================================================
# Driver
# ============================================================================
def create_casio_driver(headless: bool = False):
    """casio 専用 anonymous chrome driver 起動.

    mercari_seller anti-detection (UCD + 永続 profile + ja lang) は流用、
    casio 固有: HTTP2 protocol error 対策で **--disable-http2** flag 追加
    (= 6/1 retry で MR-G / MT-G / MTG-B 系 page で ERR_HTTP2_PROTOCOL_ERROR
    多発、 HTTP/1.1 強制で復旧確認)。
    """
    try:
        import undetected_chromedriver as uc  # noqa: PLC0415
    except ImportError as e:
        raise RuntimeError(
            "undetected_chromedriver 未インストール。 pip install undetected-chromedriver"
        ) from e

    os.makedirs(CHROME_PROFILE_DIR_CASIO, exist_ok=True)
    options = uc.ChromeOptions()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--lang=ja-JP")
    options.add_argument(f"--user-data-dir={CHROME_PROFILE_DIR_CASIO}")
    # CalculateNativeWinOcclusion + Http2 を一括 disable (= MR-G/MT-G page で
    # ERR_HTTP2_PROTOCOL_ERROR 多発、 HTTP/1.1 fallback で復旧確認 6/1)
    options.add_argument("--disable-features=CalculateNativeWinOcclusion,Http2")
    if headless:
        options.add_argument("--headless=new")

    # mercari_likes と同 Chrome version (= 148)
    driver = uc.Chrome(options=options, version_main=148)
    return driver


# ============================================================================
# URL
# ============================================================================
def build_series_url(type_slug: str) -> str:
    """type slug → series page URL.

    type_slug 例: '6900', '5600', 'mt-g', 'gw-m5610' (= 大文字小文字 / ハイフンは
    そのまま保持、 SUBSERIES → TYPE 変換は呼出側で実施)
    """
    return CASIO_SERIES_URL_TEMPLATE.format(type_slug=type_slug.lower())


def parse_model_id(url: str) -> Optional[str]:
    """Casio product URL から model_id 抽出.

    例: https://www.casio.com/jp/watches/gshock/product.DW-6900AKA-4/
        → "DW-6900AKA-4"
    """
    if not url:
        return None
    m = CASIO_PRODUCT_URL_RE.search(url)
    if m:
        return m.group(1).upper()
    return None


# ============================================================================
# Page status (= 200 / 404 / blocked 判定)
# ============================================================================
def _classify_page(driver) -> str:
    """現在 page を 'ok' / '404' / 'blocked' / 'unknown' に分類."""
    try:
        body_text = driver.execute_script(
            "return document.body.innerText.slice(0, 1000);"
        ) or ""
    except Exception:
        body_text = ""
    try:
        title = driver.title or ""
    except Exception:
        title = ""

    text_lower = (body_text + " " + title).lower()
    if any(kw in text_lower for kw in BLOCKED_MARKERS):
        return "blocked"
    if any(kw in text_lower for kw in NOT_FOUND_MARKERS):
        return "404"
    if any(kw.lower() in text_lower for kw in CHROME_ERROR_MARKERS):
        return "chrome_error"
    return "ok"


# ============================================================================
# Series page → variant list
# ============================================================================
def collect_variants_from_series_page(driver) -> list[dict]:
    """series page から variant 一覧 (= model_id / URL / 画像 / badge) 抽出.

    変化 listing 全件取得: a[href*='/product.'] かつ casio.com/jp/watches/gshock domain。
    Returns: [{model_id, url, badge, image_url}, ...]
    """
    try:
        anchors = driver.find_elements(By.CSS_SELECTOR, "a[href*='/product.']")
    except Exception:
        return []
    seen: set[str] = set()
    variants: list[dict] = []
    for a in anchors:
        try:
            href = a.get_attribute("href") or ""
        except Exception:
            continue
        if "casio.com/jp/watches/gshock/product." not in href:
            continue
        model_id = parse_model_id(href)
        if not model_id or model_id in seen:
            continue
        seen.add(model_id)
        # badge (= "NEW" / "抽選申込受付中" 等)
        try:
            badge_text = (a.text or "").strip()
        except Exception:
            badge_text = ""
        # 画像 (= 直接 <a> 内 <img> または 親要素内)
        img_src = ""
        try:
            imgs = a.find_elements(By.TAG_NAME, "img")
            for img in imgs:
                src = img.get_attribute("src") or img.get_attribute("data-src") or ""
                if src and "casio" in src:
                    img_src = src
                    break
        except Exception:
            pass
        # canonical URL (= query / fragment 除去)
        canon_url = href.split("?")[0].split("#")[0].rstrip("/")
        variants.append({
            "model_id": model_id,
            "url": canon_url,
            "badge": badge_text,
            "image_url": img_src,
        })
    return variants


# ============================================================================
# Fetch series (= 1 series page を開いて variant list 取得)
# ============================================================================
def fetch_series(
    driver,
    type_slug: str,
    initial_wait_sec: int = DEFAULT_INITIAL_WAIT_SEC,
    backoff_schedule: tuple = DEFAULT_BACKOFF_SCHEDULE_SEC,
) -> dict:
    """1 series page (= /type/<slug>/all/) を開いて結果分類 + variant list 取得.

    Returns:
        {
            "type_slug": str,
            "url": str,
            "status": "ok" | "404" | "blocked",
            "variants": list[dict],  # ok 時のみ非空
            "fetched_at": ISO8601 str,
        }
    """
    url = build_series_url(type_slug)
    try:
        driver.get(url)
    except Exception as e:
        return {
            "type_slug": type_slug,
            "url": url,
            "status": "error",
            "error": str(e),
            "variants": [],
            "fetched_at": datetime.utcnow().isoformat(),
        }

    time.sleep(initial_wait_sec)
    status = _classify_page(driver)

    # blocked 検出時 adaptive backoff (= 5s → 10s → 20s リトライ)
    if status == "blocked":
        for backoff_sec in backoff_schedule:
            time.sleep(backoff_sec)
            try:
                driver.get(url)
            except Exception:
                continue
            time.sleep(initial_wait_sec)
            status = _classify_page(driver)
            if status != "blocked":
                break

    variants: list[dict] = []
    if status == "ok":
        variants = collect_variants_from_series_page(driver)

    return {
        "type_slug": type_slug,
        "url": url,
        "status": status,
        "variants": variants,
        "fetched_at": datetime.utcnow().isoformat(),
    }


# ============================================================================
# JSON dump
# ============================================================================
def dump_series_result(result: dict, output_dir: str = DUMP_DIR) -> str:
    """fetch_series 結果を JSON ファイルに dump、 file path 返却.

    形式 (= 依頼書 sec 3-2、 ShockBase batch dump 互換):
        series_<type_slug>_<timestamp>.json
    各 variant record:
        __model__ / __series__ / __subseries__ / __url__ / __fetched_at__ / 等
    """
    os.makedirs(output_dir, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
    type_slug = result.get("type_slug", "unknown")
    file_path = os.path.join(output_dir, f"series_{type_slug}_{ts}.json")

    # ShockBase 互換 record 化
    records: list[dict] = []
    for v in result.get("variants") or []:
        records.append({
            "__model__": v.get("model_id"),
            "__series__": type_slug,
            "__subseries__": "",  # = 詳細 page まで掘らないと不明、 POC は空
            "__url__": v.get("url"),
            "__fetched_at__": result.get("fetched_at"),
            "BADGE": v.get("badge", ""),
            "IMAGE_URL": v.get("image_url", ""),
            # MSRP_JPY / RELEASE_DATE / IMAGES / IS_LIMITED / IS_NEW / MODULE 等は
            # 詳細 page まで掘ったときに追記、 POC レベルでは空
        })
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    return file_path


# ============================================================================
# all-linup page から全 variant URL を scroll で抽出 (= Option A 採用 戦略)
# ============================================================================
def _collect_variant_urls_from_page(driver) -> list[dict]:
    """現在 page から www.casio.com/jp/watches/gshock/product.<MODEL>/ URL 全件抽出.

    Returns: [{model_id, url, badge, image_url}, ...] (= dedupe + 順序保持)
    """
    try:
        anchors = driver.find_elements(By.CSS_SELECTOR, "a[href*='/product.']")
    except Exception:
        return []
    seen: set[str] = set()
    variants: list[dict] = []
    for a in anchors:
        try:
            href = a.get_attribute("href") or ""
        except Exception:
            continue
        if "casio.com/jp/watches/gshock/product." not in href:
            continue
        model_id = parse_model_id(href)
        if not model_id or model_id in seen:
            continue
        seen.add(model_id)
        try:
            badge_text = (a.text or "").strip()
        except Exception:
            badge_text = ""
        img_src = ""
        try:
            imgs = a.find_elements(By.TAG_NAME, "img")
            for img in imgs:
                src = img.get_attribute("src") or img.get_attribute("data-src") or ""
                if src:
                    img_src = src
                    break
        except Exception:
            pass
        canon_url = href.split("?")[0].split("#")[0].rstrip("/")
        variants.append({
            "model_id": model_id,
            "url": canon_url,
            "badge": badge_text,
            "image_url": img_src,
        })
    return variants


def fetch_all_linup(
    driver,
    initial_wait_sec: int = DEFAULT_INITIAL_WAIT_SEC,
    scroll_interval_sec: float = ALL_LINUP_SCROLL_INTERVAL_SEC,
    no_progress_threshold: int = ALL_LINUP_NO_PROGRESS_THRESHOLD,
    max_scrolls: int = ALL_LINUP_MAX_SCROLLS,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> dict:
    """all-linup page を開いて scroll で全 G-shock variant URL を取得.

    5/31 Option A 戦略: TYPE 単位 loop 不要、 all-linup 1 page で完結。

    Returns:
        {
            "url": ALL_LINUP_URL,
            "status": "ok" | "blocked" | "error",
            "variants": list[dict],
            "scroll_progression": list[int],
            "fetched_at": ISO8601 str,
        }
    """
    try:
        driver.get(ALL_LINUP_URL)
    except Exception as e:
        return {
            "url": ALL_LINUP_URL,
            "status": "error",
            "error": str(e),
            "variants": [],
            "scroll_progression": [],
            "fetched_at": datetime.utcnow().isoformat(),
        }
    time.sleep(initial_wait_sec)
    status = _classify_page(driver)
    if status != "ok":
        return {
            "url": ALL_LINUP_URL,
            "status": status,
            "variants": [],
            "scroll_progression": [],
            "fetched_at": datetime.utcnow().isoformat(),
        }
    # scroll loop = 増加停止まで
    progression: list[int] = []
    last_count = len(_collect_variant_urls_from_page(driver))
    progression.append(last_count)
    no_progress = 0
    for i in range(max_scrolls):
        try:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        except Exception:
            pass
        time.sleep(scroll_interval_sec)
        current = len(_collect_variant_urls_from_page(driver))
        progression.append(current)
        if progress_callback:
            try:
                progress_callback(i + 1, current, f"scroll #{i+1}: {current} variants")
            except Exception:
                pass
        if current == last_count:
            no_progress += 1
            if no_progress >= no_progress_threshold:
                break
        else:
            no_progress = 0
        last_count = current
    variants = _collect_variant_urls_from_page(driver)
    return {
        "url": ALL_LINUP_URL,
        "status": "ok",
        "variants": variants,
        "scroll_progression": progression,
        "fetched_at": datetime.utcnow().isoformat(),
    }


def dump_all_linup_result(result: dict, output_dir: str = DUMP_DIR) -> str:
    """fetch_all_linup 結果を JSON ファイルに dump、 file path 返却.

    ShockBase 互換 record 形式:
        all_linup_<timestamp>.json
    """
    os.makedirs(output_dir, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
    file_path = os.path.join(output_dir, f"all_linup_{ts}.json")
    records: list[dict] = []
    fetched_at = result.get("fetched_at")
    for v in result.get("variants") or []:
        records.append({
            "__model__": v.get("model_id"),
            "__series__": "",  # = all-linup から取れる範囲では未確定 (= TYPE 推定別途)
            "__subseries__": "",
            "__url__": v.get("url"),
            "__fetched_at__": fetched_at,
            "BADGE": v.get("badge", ""),
            "IMAGE_URL": v.get("image_url", ""),
        })
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    return file_path


# ============================================================================
# Variant detail page status check (= 5/31 unmatched 44 件 検証 用)
# ============================================================================
def fetch_detail_status(
    driver,
    detail_url: str,
    initial_wait_sec: int = 8,
) -> dict:
    """1 variant detail URL を開いて status (= 200 / 404 / redirect / error) 判定.

    200 OK 時は title + image_url + 価格 (= 取れれば) を抽出。

    Returns:
        {
            "url": str,
            "status": "200" | "404" | "redirect" | "blocked" | "error",
            "current_url": str,
            "title": str,
            "image_url": str,
            "price_text": str,
            "fetched_at": ISO8601 str,
        }
    """
    result = {
        "url": detail_url,
        "status": "error",
        "current_url": "",
        "title": "",
        "image_url": "",
        "price_text": "",
        "fetched_at": datetime.utcnow().isoformat(),
    }
    try:
        driver.get(detail_url)
    except Exception as e:
        result["error"] = str(e)
        return result
    time.sleep(initial_wait_sec)
    try:
        current_url = driver.current_url or ""
    except Exception:
        current_url = ""
    result["current_url"] = current_url
    status = _classify_page(driver)
    if status == "blocked":
        result["status"] = "blocked"
        return result
    if status == "404":
        result["status"] = "404"
        return result
    # redirect 判定 (= 入力 URL と current_url の host/path 不一致)
    try:
        in_path = detail_url.split("?")[0].split("#")[0].rstrip("/")
        cur_path = current_url.split("?")[0].split("#")[0].rstrip("/")
        if in_path.lower() != cur_path.lower():
            result["status"] = "redirect"
            # redirect 先が 404 の可能性 → 中身 fetch しない
            return result
    except Exception:
        pass
    # 200 OK 想定 → title + image + 価格抽出
    result["status"] = "200"
    try:
        title = driver.title or ""
    except Exception:
        title = ""
    result["title"] = title
    # h1 / 商品名
    try:
        h1_text = driver.execute_script("""
            const h1 = document.querySelector('h1');
            return h1 ? h1.textContent.trim().slice(0, 120) : '';
        """) or ""
        if h1_text:
            result["h1"] = h1_text
    except Exception:
        pass
    # 公式商品画像 (= 主 visual)
    try:
        img_src = driver.execute_script("""
            const imgs = Array.from(document.querySelectorAll('img'));
            for (const img of imgs) {
                const src = img.src || img.getAttribute('data-src') || '';
                if (src && (src.includes('casio.com/content') || src.includes('mercdn') || src.includes('static.casio') || src.includes('product'))) {
                    return src;
                }
            }
            return imgs.length > 0 ? (imgs[0].src || '') : '';
        """) or ""
        result["image_url"] = img_src
    except Exception:
        pass
    # 価格 (= 円 表記 候補)
    try:
        price_text = driver.execute_script("""
            const text = document.body.innerText || '';
            const m = text.match(/[¥￥]\\s*[\\d,]+\\s*円?/);
            return m ? m[0] : '';
        """) or ""
        result["price_text"] = price_text
    except Exception:
        pass
    return result


# ============================================================================
# Variant detail page から spec 抽出 (= 6/1 catalog merge 用 100 件 fetch)
# ============================================================================
# spec accordion の DOM 構造 (= 5/31 実機 dump で確定):
#   <li class="p-product_detail-spec-accordion__panel-item">
#     <div class="...panel-item-ttl"><h4>label</h4></div>
#     <div class="...panel-item-cont">value</div>
#   </li>
# label の例 (= 公式 表記):
#   "ケースサイズ（縦×横×厚さ）" / "質量" / "発売年月" / "使用電源・電池寿命"
#   / "ケース・ベゼル材質" / "バンド" / "防水性" / "耐衝撃構造"
SPEC_LI_SELECTOR = "li.p-product_detail-spec-accordion__panel-item"
SPEC_LABEL_SELECTOR = ".p-product_detail-spec-accordion__panel-item-ttl h4"
SPEC_VALUE_SELECTOR = ".p-product_detail-spec-accordion__panel-item-cont"

# label → output field 名の mapping (= 依頼書 sec 3 の schema に合わせる)
# fail-closed: mapping に無い label は無視 (= 推測で埋めない)
SPEC_LABEL_TO_FIELD = {
    "ケースサイズ（縦×横×厚さ）": "size",
    "ケースサイズ": "size",
    "質量": "weight",
    "発売年月": "release_date",
    "使用電源・電池寿命": "battery",
    "ケース・ベゼル材質": "material_case_bezel",
    "ケース材質": "material_case",
    "ベゼル材質": "material_bezel",
    "バンド": "material_band",
    "ベルト": "material_band",
    "防水性": "water_resistance",
    "耐衝撃構造": "shock_resistance",
    "構造": "shock_resistance",
    "ガラス": "glass",
    "モジュール": "module",
    "ムーブメント": "module",
    "電波受信機能": "radio_wave",
    "ソーラー": "solar",
    "Bluetooth": "bluetooth",
}


def fetch_detail_spec(
    driver,
    detail_url: str,
    initial_wait_sec: int = 12,
) -> dict:
    """Casio variant detail page から spec 抽出 (= ShockBase 互換 schema).

    DOM 構造: spec accordion (= li.p-product_detail-spec-accordion__panel-item)
    抽出項目 (= 依頼書 2026-06-01_casio_official_100_detail_fetch sec 3):
    - MSRP_JPY / RELEASE_DATE / MODULE / MATERIAL_* / WATER_RESISTANCE / WEIGHT / SIZE
    - 主画像 + 追加画像 URL

    Returns:
        {
            "url": str,
            "status": "200" | "404" | "redirect" | "blocked" | "error",
            "title": str,
            "h1": str,
            "msrp_jpy": str,
            "release_date": str,
            "module": str,
            "material_band": str,
            "material_bezel": str,
            "material_case": str,
            "material_case_bezel": str,
            "water_resistance": str,
            "weight": str,
            "size": str,
            "battery": str,
            "shock_resistance": str,
            "main_image": str,
            "additional_images": list[str],
            "raw_specs": dict[label, value],  # = 全 spec ペア (= mapping 漏れ調査用)
            "fetched_at": ISO8601 str,
        }
    """
    from selenium.common.exceptions import WebDriverException  # noqa: PLC0415

    result = {
        "url": detail_url,
        "status": "error",
        "title": "",
        "h1": "",
        "msrp_jpy": "",
        "release_date": "",
        "module": "",
        "glass": "",
        "material_band": "",
        "material_bezel": "",
        "material_case": "",
        "material_case_bezel": "",
        "water_resistance": "",
        "weight": "",
        "size": "",
        "battery": "",
        "shock_resistance": "",
        "main_image": "",
        "additional_images": [],
        "raw_specs": {},
        "fetched_at": datetime.utcnow().isoformat(),
    }
    # chrome HTTP2 protocol error 等で初回 fetch 失敗するケースの retry (= 6/1 MR-G 系)
    # 3 回 retry、 各 retry 間 5s/10s/15s で指数 backoff
    status = "error"
    backoff_secs = (5.0, 10.0, 15.0)
    for retry_idx in range(3):
        try:
            driver.get(detail_url)
        except WebDriverException as e:
            result["error"] = str(e)
            if retry_idx == 2:
                return result
            time.sleep(backoff_secs[retry_idx])
            continue
        time.sleep(initial_wait_sec)
        status = _classify_page(driver)
        if status != "chrome_error":
            break
        # chrome 側 protocol error 検出 → backoff 後 retry
        if retry_idx < 2:
            time.sleep(backoff_secs[retry_idx])
    if status == "blocked":
        result["status"] = "blocked"
        return result
    if status == "404":
        result["status"] = "404"
        return result
    if status == "chrome_error":
        result["status"] = "chrome_error"
        return result
    result["status"] = "200"

    # title / h1
    try:
        result["title"] = driver.title or ""
    except Exception:
        pass
    try:
        h1 = driver.execute_script(
            "return (document.querySelector('h1')?.textContent || '').trim();"
        )
        result["h1"] = h1 or ""
    except Exception:
        pass

    # spec accordion 全件抽出 → label/value ペア
    try:
        pairs = driver.execute_script(f"""
            const items = document.querySelectorAll({json.dumps(SPEC_LI_SELECTOR)});
            const out = [];
            items.forEach(li => {{
                const lab = li.querySelector({json.dumps(SPEC_LABEL_SELECTOR)});
                const val = li.querySelector({json.dumps(SPEC_VALUE_SELECTOR)});
                const labText = lab ? (lab.textContent || '').trim() : '';
                const valText = val ? (val.textContent || '').trim() : '';
                if (labText) out.push({{label: labText, value: valText}});
            }});
            return out;
        """) or []
    except Exception:
        pairs = []
    for p in pairs:
        label = p.get("label") or ""
        value = (p.get("value") or "").strip()
        result["raw_specs"][label] = value
        field = SPEC_LABEL_TO_FIELD.get(label)
        if field:
            result[field] = value

    # 価格 (= span.price-label の親要素から ¥ 表記抽出)
    try:
        msrp = driver.execute_script("""
            const lab = document.querySelector('span.price-label');
            if (!lab) return '';
            // 親 / 親の親内の ¥/￥ 含む text
            let node = lab.parentElement;
            for (let i = 0; i < 4 && node; i++) {
                const t = node.textContent || '';
                const m = t.match(/[¥￥]\\s*([\\d,]+)\\s*円?/);
                if (m) return m[0];
                node = node.parentElement;
            }
            return '';
        """) or ""
        result["msrp_jpy"] = msrp
    except Exception:
        pass

    # 画像: JSON-LD (= schema.org Product image) を主画像、 page 内 product 画像も追加
    try:
        ld_json = driver.execute_script("""
            const scripts = document.querySelectorAll('script[type="application/ld+json"]');
            for (const s of scripts) {
                try {
                    const j = JSON.parse(s.textContent);
                    if (j && j['@type'] === 'Product') return j;
                } catch (e) {}
            }
            return null;
        """)
    except Exception:
        ld_json = None
    if ld_json and isinstance(ld_json, dict):
        img = ld_json.get("image")
        if isinstance(img, str):
            result["main_image"] = img
        elif isinstance(img, list) and img:
            result["main_image"] = img[0]
            result["additional_images"] = [u for u in img[1:] if isinstance(u, str)]
    if not result["main_image"]:
        # fallback: img.src で casio CDN を含むもの最初
        try:
            img = driver.execute_script("""
                const imgs = Array.from(document.querySelectorAll('img'));
                for (const i of imgs) {
                    const s = i.src || i.getAttribute('data-src') || '';
                    if (s && (s.includes('casio.com/content') || s.includes('static.casio'))) return s;
                }
                return imgs.length > 0 ? (imgs[0].src || '') : '';
            """) or ""
            result["main_image"] = img
        except Exception:
            pass

    return result


# ============================================================================
# POC = 複数 series fetch + 統計集計
# ============================================================================
def run_poc(
    type_slugs: list[str],
    headless: bool = False,
    rate_limit_min_sec: float = DEFAULT_REQUEST_RATE_LIMIT_MIN_SEC,
    rate_limit_max_sec: float = DEFAULT_REQUEST_RATE_LIMIT_MAX_SEC,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> dict:
    """複数 series を POC 取得、 統計 + dump path list 返却.

    Returns:
        {
            "total": N,
            "ok": M,
            "404": P,
            "blocked": Q,
            "error": R,
            "total_variants": V,
            "per_series": [{type_slug, status, n_variants, file_path}, ...],
        }
    """
    driver = create_casio_driver(headless=headless)
    try:
        try:
            driver.maximize_window()
        except Exception:
            pass
        per_series: list[dict] = []
        ok_count = 0
        not_found_count = 0
        blocked_count = 0
        error_count = 0
        total_variants = 0
        total = len(type_slugs)
        for i, slug in enumerate(type_slugs, start=1):
            if progress_callback:
                try:
                    progress_callback(i, total, slug)
                except Exception:
                    pass
            result = fetch_series(driver, slug)
            file_path = ""
            if result["status"] == "ok":
                ok_count += 1
                total_variants += len(result.get("variants") or [])
                file_path = dump_series_result(result)
            elif result["status"] == "404":
                not_found_count += 1
            elif result["status"] == "blocked":
                blocked_count += 1
            else:
                error_count += 1
            per_series.append({
                "type_slug": slug,
                "status": result["status"],
                "n_variants": len(result.get("variants") or []),
                "file_path": file_path,
                "url": result.get("url"),
            })
            # rate limit (= 詳細取得 / 次 series 間)
            if i < total and rate_limit_max_sec > 0:
                time.sleep(random.uniform(rate_limit_min_sec, rate_limit_max_sec))
        return {
            "total": total,
            "ok": ok_count,
            "404": not_found_count,
            "blocked": blocked_count,
            "error": error_count,
            "total_variants": total_variants,
            "per_series": per_series,
        }
    finally:
        try:
            driver.quit()
        except Exception:
            pass
