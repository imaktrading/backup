"""login_with_chromium - trabajo の Chromium portable を借りて eBay 手動 login.

目的: uc.Chrome (= Google Chrome) では eBay anti-bot CAPTCHA が通らない問題を、
      Chromium portable で迂回できるか検証する。

手順:
  1. chrome_profile_ebay を退避 (空状態から)
  2. trabajo の chromep.exe を browser_executable_path で起動
  3. eBay signin ページ表示
  4. Takaaki さんが手動 login (Stay signed in チェック必須)
  5. is_logged_in 確認 → 成功なら exit
  6. chrome quit 時に profile dir に cookie が焼かれる

実行: python debug/login_with_chromium.py
"""
from __future__ import annotations

import os
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CHROMIUM_PATH = r"C:\トラバホセット\BoostListing（出品・在庫管理一体型ツール）\BoostListing\BoostListing\chrome\chromep.exe"
CHROMEDRIVER_PATH = r"C:\トラバホセット\BoostListing（出品・在庫管理一体型ツール）\BoostListing\BoostListing\dll\chromedriver.exe"
PROFILE_DIR = r"C:\Users\imax2\local_data\iMakInventory\chrome_profile_ebay"
PROFILE_BACKUP_BASE = r"C:\Users\imax2\local_data\iMakInventory\chrome_profile_ebay_bak"

EBAY_SIGNIN_URL = "https://signin.ebay.com/ws/eBayISAPI.dll?SignIn"
EBAY_HOME = "https://www.ebay.com/"


def backup_profile() -> str:
    """既存 profile を rename 退避."""
    if not os.path.exists(PROFILE_DIR):
        return ""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = f"{PROFILE_BACKUP_BASE}_{ts}"
    print(f"[1/4] profile backup: {PROFILE_DIR} -> {bak}")
    os.rename(PROFILE_DIR, bak)
    return bak


def is_logged_in(driver) -> bool:
    """eBay ログイン状態判定 (URL に signin 含まない and Hi <username> 表示)."""
    try:
        cur = driver.current_url
        if "signin" in cur.lower():
            return False
        body = driver.find_element_by_tag_name("body").text if hasattr(driver, "find_element_by_tag_name") else ""
        if not body:
            from selenium.webdriver.common.by import By  # noqa: PLC0415
            body = driver.find_element(By.TAG_NAME, "body").text
        # eBay 上部のサインイン状態表示
        if "Hi" in body and "Sign in" not in body[:200]:
            return True
        return False
    except Exception:
        return False


def main():
    if not os.path.exists(CHROMIUM_PATH):
        print(f"[NG] chromep.exe not found: {CHROMIUM_PATH}")
        sys.exit(1)
    print(f"[INFO] using Chromium: {CHROMIUM_PATH}")

    bak = backup_profile()
    os.makedirs(PROFILE_DIR, exist_ok=True)

    print(f"[2/4] uc.Chrome with browser_executable_path...")
    try:
        import undetected_chromedriver as uc  # noqa: PLC0415
    except ImportError:
        print("[NG] undetected_chromedriver not installed")
        sys.exit(2)

    options = uc.ChromeOptions()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--lang=en-US")
    options.add_argument("--start-maximized")
    options.add_argument(f"--user-data-dir={PROFILE_DIR}")

    # Chromium portable = 136 系。trabajo 同梱 chromedriver.exe 136 を直接指定で download 回避
    driver = uc.Chrome(
        options=options,
        browser_executable_path=CHROMIUM_PATH,
        driver_executable_path=CHROMEDRIVER_PATH,
        version_main=136,
    )

    try:
        print(f"[3/4] open eBay signin page...")
        driver.get(EBAY_SIGNIN_URL)
        print()
        print("=" * 60)
        print(" Takaaki さん操作お願いします:")
        print("   1. Email / Password 入力")
        print("   2. 'Stay signed in' チェックボックス ON 必須 (= 永続 cookie 焼く)")
        print("   3. Sign in click")
        print("   4. CAPTCHA / 2FA が出たら通常通り操作")
        print("   5. eBay top に着いたらこの window を閉じずに待機")
        print("=" * 60)
        print()
        print("[4/4] login 完了 polling (最大 300 秒)...")

        for i in range(60):
            time.sleep(5)
            if is_logged_in(driver):
                print(f"  [OK] login 完了確認 ({i*5}s 経過)")
                print(f"  current_url: {driver.current_url}")
                # cookie 焼くため少し待機 + ホームに遷移
                driver.get(EBAY_HOME)
                time.sleep(5)
                print("  cookie 焼き付け完了、driver quit します")
                return 0
            if i % 6 == 0:
                print(f"    待機中 ({i*5}s)... current_url: {driver.current_url[:80]}")

        print("  [NG] 300 秒経過、login 完了確認できず")
        return 3
    finally:
        try:
            driver.quit()
        except Exception:
            pass
        print()
        if bak:
            print(f"[INFO] 旧 profile は退避済: {bak}")
            print(f"       問題あれば: rm -r {PROFILE_DIR} && mv {bak} {PROFILE_DIR}")


if __name__ == "__main__":
    sys.exit(main())
