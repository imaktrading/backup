"""Phase 7.1 Fril scraper 着手: HTML 検体収集.

TEST_LOW row 652-661 の Fril URL を Selenium で render し、HTML 保存。
Takaaki さんが各 URL の目視結果 (in_stock / sold) を教えた後、差分分析へ進む。
"""
from __future__ import annotations
import os, sys, time, re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException

from sheet_updater import open_sheet_by_id, get_listings_worksheet, read_listings_rows

PROFILE = r"C:\Users\imax2\local_data\iMakMercari\chrome_profile"
SAMPLES = ROOT / "debug" / "fril_samples"
SAMPLES.mkdir(parents=True, exist_ok=True)

TEST_LOW_ID = "1wjiTTRodh1yPI8NoD4zU4ZN6fcXDBY9oZmhT5Ycf120"


def main():
    sh = open_sheet_by_id(TEST_LOW_ID)
    ws = get_listings_worksheet(sh)
    rows = read_listings_rows(ws, start_row=652, end_row=661, only_with_url=True)
    fril = [r for r in rows if 'fril.jp' in (r['url'] or '')]
    print(f"Fril URL: {len(fril)} 件")

    options = uc.ChromeOptions()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--lang=ja-JP")
    options.add_argument(f"--user-data-dir={PROFILE}")
    options.add_argument("--headless=new")
    options.add_argument("--window-size=1280,1800")
    d = uc.Chrome(options=options, version_main=146)
    try:
        for r in fril:
            url = r['url']
            row_idx = r['row_index']
            # extract product id from URL (last path segment)
            m = re.search(r'/([\w-]+)(?:\?|$)', url)
            pid = m.group(1) if m else f"row{row_idx}"
            print(f"\n[row{row_idx}] {url}")
            try:
                d.get(url)
                # Fril 用 hydration 待ち候補 testid を順次試す
                hydrate_testids = ["item-detail", "item-name", "product-detail", "main", "checkout-button"]
                start_at = time.time()
                hydrated = False
                while time.time() - start_at < 25:
                    body_text = d.find_element(By.TAG_NAME, "body").text or ""
                    if len(body_text) > 1500:  # ある程度 render されたら OK
                        hydrated = True
                        break
                    time.sleep(0.5)
                time.sleep(2)
                html = d.page_source
                path = SAMPLES / f"row{row_idx}_{pid}.html"
                path.write_text(html, encoding="utf-8", errors="replace")
                # png also
                try:
                    d.save_screenshot(str(SAMPLES / f"row{row_idx}_{pid}.png"))
                except Exception:
                    pass
                # quick stat
                title_m = re.search(r'<title>(.+?)</title>', html, re.DOTALL)
                title = title_m.group(1).strip() if title_m else "(no title)"
                print(f"  hydrated: {hydrated}, len: {len(html)}, title: {title[:60]}")
            except Exception as e:
                print(f"  err: {type(e).__name__}: {e}")
    finally:
        try: d.quit()
        except: pass

    print(f"\n=== 完了: 検体は {SAMPLES} ===")


if __name__ == "__main__":
    main()
