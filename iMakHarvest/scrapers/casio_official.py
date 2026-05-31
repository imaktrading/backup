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

# 出力先 (= 依頼書 sec 3-2)
DUMP_DIR = r"C:\dev\iMak_data\catalog\_casio_official_dumps"


# ============================================================================
# Driver
# ============================================================================
def create_casio_driver(headless: bool = False):
    """casio 専用 anonymous chrome driver 起動 (= mercari_seller と同じ create_driver 流用)."""
    os.makedirs(CHROME_PROFILE_DIR_CASIO, exist_ok=True)
    return mercari_likes.create_driver(
        headless=headless, profile_dir=CHROME_PROFILE_DIR_CASIO,
    )


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
