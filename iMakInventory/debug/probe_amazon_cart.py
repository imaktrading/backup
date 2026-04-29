"""Amazon HTML 検体収集 (in_stock 確認済 + 既存判定 sold な URL).

Cart button selector を見つけるための probe.
"""
import sys, time, re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import requests
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

import undetected_chromedriver as uc

PROFILE = r"C:\Users\imax2\local_data\iMakMercari\chrome_profile"
SAMPLES = ROOT / "debug" / "amazon_samples"
SAMPLES.mkdir(parents=True, exist_ok=True)

# 「在庫あり」と Takaaki さん目視確認の URL
URLS_IN_STOCK = [
    ("anello_B0BNHJJSZ6", "https://www.amazon.co.jp/dp/B0BNHJJSZ6/"),
    ("anello_B0BNHR7J1X", "https://www.amazon.co.jp/dp/B0BNHR7J1X/"),
    ("anello_B0D1C2146V", "https://www.amazon.co.jp/dp/B0D1C2146V/"),
]

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
HDRS = {"User-Agent": UA, "Accept-Language": "ja-JP,ja;q=0.9,en;q=0.5",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}


def probe_requests(label, url):
    print(f"\n=== [requests] {label}: {url} ===")
    try:
        r = requests.get(url, headers=HDRS, timeout=20)
        print(f"  status: {r.status_code}, len: {len(r.text)}")
        # save
        path = SAMPLES / f"requests_{label}.html"
        path.write_text(r.text, encoding="utf-8", errors="replace")
        print(f"  saved: {path}")
        # check for cart button markers
        markers = {
            "id=\"add-to-cart-button\"":   r.text.count('id="add-to-cart-button"'),
            "name=\"submit.add-to-cart\"": r.text.count('name="submit.add-to-cart"'),
            "カートに入れる":              r.text.count("カートに入れる"),
            "今すぐ買う":                  r.text.count("今すぐ買う"),
            "Add to Cart":                 r.text.count("Add to Cart"),
            "現在お取り扱いできません":    r.text.count("現在お取り扱いできません"),
            "在庫切れ":                    r.text.count("在庫切れ"),
            "在庫あり":                    r.text.count("在庫あり"),
            "通常配送無料":                r.text.count("通常配送無料"),
            "captcha":                     r.text.lower().count("captcha"),
            "Type the characters":         r.text.count("Type the characters"),
        }
        for k, v in markers.items():
            if v > 0:
                print(f"  [{v}] {k}")
    except Exception as e:
        print(f"  err: {type(e).__name__}: {e}")


def probe_selenium(driver, label, url):
    print(f"\n=== [selenium] {label}: {url} ===")
    try:
        driver.get(url)
        time.sleep(8)
        html = driver.page_source
        path = SAMPLES / f"selenium_{label}.html"
        path.write_text(html, encoding="utf-8", errors="replace")
        print(f"  rendered len: {len(html)}, saved: {path}")
        # check elements
        selectors = [
            ('#add-to-cart-button',                 'css'),
            ('input[name="submit.add-to-cart"]',    'css'),
            ('#buy-now-button',                     'css'),
            ('//button[contains(text(),"カートに入れる")]', 'xpath'),
            ('//*[@id="availability"]',             'xpath'),
            ('//*[contains(text(),"現在お取り扱いできません")]', 'xpath'),
        ]
        for sel, kind in selectors:
            try:
                if kind == 'css':
                    elem = driver.find_element(By.CSS_SELECTOR, sel)
                else:
                    elem = driver.find_element(By.XPATH, sel)
                txt = (elem.text or "").strip()[:60]
                vis = elem.is_displayed()
                print(f"  ✓ FOUND {sel} (visible={vis}) text='{txt}'")
            except Exception:
                print(f"  ✗ NOT FOUND {sel}")
    except Exception as e:
        print(f"  err: {type(e).__name__}: {e}")


def main():
    # requests path
    for label, url in URLS_IN_STOCK:
        probe_requests(label, url)

    # selenium path
    opts = uc.ChromeOptions()
    opts.add_argument("--no-sandbox")
    opts.add_argument(f"--user-data-dir={PROFILE}")
    opts.add_argument("--lang=ja-JP")
    opts.add_argument("--headless=new")
    opts.add_argument("--window-size=1280,1800")
    d = uc.Chrome(options=opts, version_main=146)
    try:
        for label, url in URLS_IN_STOCK:
            probe_selenium(d, label, url)
    finally:
        try: d.quit()
        except: pass


if __name__ == "__main__":
    main()
