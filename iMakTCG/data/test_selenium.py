#!/usr/bin/env python3
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager
import time

options = Options()
# ヘッドレスなし（画面表示あり）

driver = webdriver.Chrome(
    service=Service(ChromeDriverManager().install()),
    options=options
)

print("Chromeが開きました。PSA Japanにアクセスします...")
driver.get("https://www.psacard.com/ja-JP/cert/139075607/psa")
print(f"URL: {driver.current_url}")
time.sleep(5)

print(f"Title: {driver.title}")
body = driver.find_element(By.TAG_NAME, "body").text
print(f"\nページテキスト（最初の500文字）:\n{body[:500]}")

driver.quit()
input("\nEnterで終了...")
