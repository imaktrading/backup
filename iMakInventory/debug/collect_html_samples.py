"""Phase 1: HTML / PNG 検体収集 (mercari_scraper 精度問題の差分分析用).

各 URL を Selenium で開き、testid='product-detail' 描画完了後に outerHTML と
スクショを inventory/debug/html_samples/{in_stock|sold}_{item_id}.{html,png} に保存。

待機: WebDriverWait 30秒、それでも product-detail 見えなければ "real_err" ログ
(検体から除外、実物比較の noise を避ける)。

Note: 過去 probe では `product-detail` testid は確認できず、`item-detail-container`
のみ見えていた。本スクリプトは両方候補にして wait し、見えた最初の testid を採用する。
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException

SAMPLES_DIR = Path(__file__).resolve().parent / "html_samples"
SAMPLES_DIR.mkdir(parents=True, exist_ok=True)

CHROME_PROFILE_DIR = r"C:\Users\imax2\local_data\iMakMercari\chrome_profile"
CHROME_VERSION_MAIN = 146

# Phase 1 で待つ testid 候補 (最初に見えたものを採用)
HYDRATION_TESTIDS = ["product-detail", "item-detail-container", "item-name", "display-name"]
WAIT_SEC = 30

IN_STOCK_URLS = [
    "https://jp.mercari.com/item/m13033508222",
    "https://jp.mercari.com/item/m49383173561",
    "https://jp.mercari.com/item/m82262228708",
    "https://jp.mercari.com/item/m64819241726",
    "https://jp.mercari.com/item/m85731918507",
    "https://jp.mercari.com/item/m64454009245",
    "https://jp.mercari.com/item/m34502758783",
    "https://jp.mercari.com/item/m41555692668",
    "https://jp.mercari.com/item/m27139398286",
    "https://jp.mercari.com/item/m76741283035",
    "https://jp.mercari.com/item/m12964510802",
]

SOLD_URLS = [
    "https://jp.mercari.com/item/m96600846115",
    "https://jp.mercari.com/item/m63571237049",
    "https://jp.mercari.com/item/m63905828803",
    "https://jp.mercari.com/item/m32993695536",
    "https://jp.mercari.com/item/m69015839424",
    "https://jp.mercari.com/item/m59588662304",
    "https://jp.mercari.com/item/m94867178401",
    "https://jp.mercari.com/item/m42421532190",
    "https://jp.mercari.com/item/m95836277025",
    "https://jp.mercari.com/item/m99325579898",
]


def parse_item_id(url: str) -> str:
    m = re.search(r"/item/(m\d+)", url)
    return m.group(1) if m else "unknown"


def make_driver():
    options = uc.ChromeOptions()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--lang=ja-JP")
    options.add_argument(f"--user-data-dir={CHROME_PROFILE_DIR}")
    options.add_argument("--headless=new")
    options.add_argument("--window-size=1280,1800")
    return uc.Chrome(options=options, version_main=CHROME_VERSION_MAIN)


def wait_hydration(driver, url):
    """testid 候補のいずれかが描画されるまで待つ. 採用 testid 名を返す or None."""
    for tid in HYDRATION_TESTIDS:
        try:
            WebDriverWait(driver, 0.1).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, f'[data-testid="{tid}"]'))
            )
            return tid
        except TimeoutException:
            continue

    # 短い poll で待つ (各 testid 候補を順次確認、合計 WAIT_SEC まで)
    end_at = time.time() + WAIT_SEC
    while time.time() < end_at:
        for tid in HYDRATION_TESTIDS:
            try:
                driver.find_element(By.CSS_SELECTOR, f'[data-testid="{tid}"]')
                return tid
            except Exception:
                continue
        time.sleep(0.5)
    return None


def fetch_one(driver, label, url, log):
    item_id = parse_item_id(url)
    target_html = SAMPLES_DIR / f"{label}_{item_id}.html"
    target_png = SAMPLES_DIR / f"{label}_{item_id}.png"

    print(f"\n[{label}/{item_id}] {url}")
    t0 = time.time()
    try:
        driver.get(url)
    except WebDriverException as e:
        log.append({"label": label, "item_id": item_id, "url": url,
                    "status": "real_err", "error": f"driver.get: {e}"})
        print(f"  ❌ driver.get failed: {e}")
        return

    hydrate_testid = wait_hydration(driver, url)
    elapsed = time.time() - t0
    if hydrate_testid is None:
        log.append({"label": label, "item_id": item_id, "url": url,
                    "status": "real_err",
                    "error": f"hydration timeout after {WAIT_SEC}s",
                    "elapsed": elapsed})
        print(f"  ❌ hydration timeout ({WAIT_SEC}s)")
        return

    # Hydration が「商品本体」と「広告」「related」とで非同期な可能性
    # → 余裕で 2 秒待ってから snapshot
    time.sleep(2)
    try:
        html = driver.page_source
    except WebDriverException as e:
        log.append({"label": label, "item_id": item_id, "url": url,
                    "status": "real_err", "error": f"page_source: {e}"})
        print(f"  ❌ page_source failed: {e}")
        return

    target_html.write_text(html, encoding="utf-8")
    try:
        driver.save_screenshot(str(target_png))
    except WebDriverException as e:
        print(f"  ⚠️ screenshot failed (HTML 保存は成功): {e}")

    log.append({
        "label": label, "item_id": item_id, "url": url,
        "status": "ok",
        "hydrate_testid": hydrate_testid,
        "elapsed_sec": round(elapsed, 2),
        "html_size": len(html),
        "html_path": str(target_html),
        "png_path": str(target_png),
    })
    print(f"  ✅ saved (testid={hydrate_testid}, {elapsed:.1f}s, {len(html)//1024}KB)")


def main():
    driver = make_driver()
    log = []
    try:
        for url in IN_STOCK_URLS:
            fetch_one(driver, "in_stock", url, log)
        for url in SOLD_URLS:
            fetch_one(driver, "sold", url, log)
    finally:
        try:
            driver.quit()
        except Exception:
            pass

    log_path = SAMPLES_DIR / "_collection_log.json"
    log_path.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
    n_ok = sum(1 for r in log if r["status"] == "ok")
    n_err = sum(1 for r in log if r["status"] == "real_err")
    print()
    print(f"=== Phase 1 完了: {n_ok}/{len(log)} 件 ok, {n_err} real_err ===")
    print(f"  log: {log_path}")


if __name__ == "__main__":
    main()
