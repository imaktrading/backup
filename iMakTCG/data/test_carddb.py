#!/usr/bin/env python3
import time
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

options = uc.ChromeOptions()
options.add_argument("--no-sandbox")
driver = uc.Chrome(options=options, version_main=146)

print("exburst.devにアクセスします...")
driver.get("https://exburst.dev/gundam/cardlist?set=GD02")
time.sleep(8)

body = driver.find_element(By.TAG_NAME, "body").text
idx = body.find("GD02-055")
if idx >= 0:
    print("見つかりました！")
    print(body[idx-50:idx+300])
else:
    print("GD02-055 見つからず")
    # ネットワークリクエストを確認
    print(f"\nURL: {driver.current_url}")
    print(f"ページテキスト先頭:\n{body[:800]}")

driver.quit()
input("Enterで終了...")
