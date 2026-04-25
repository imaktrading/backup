#!/usr/bin/env python3
import time
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By

url = "https://1kuji.com/products/hololive-vs"

options = uc.ChromeOptions()
options.add_argument("--no-sandbox")
driver = uc.Chrome(options=options, version_main=146)

try:
    print("ページ読み込み開始...")
    driver.get(url)
    print("待機中...15秒")
    time.sleep(15)

    print(f"現在のURL: {driver.current_url}")
    print(f"タイトル: {driver.title}")

    try:
        body_text = driver.find_element(By.TAG_NAME, "body").text
        print(f"bodyテキスト長: {len(body_text)}文字")
        
        with open("kuji_debug.txt", "w", encoding="utf-8") as f:
            f.write(body_text)
        print("kuji_debug.txt 保存完了")

        # 賞確認
        for letter in ['A', 'B', 'C', 'D', 'ラストワン']:
            pattern = f'{letter}賞'
            print(f"  {pattern}: {'✅' if pattern in body_text else '❌'}")

        # 先頭500文字表示
        print("\n=== テキスト先頭500文字 ===")
        print(body_text[:500])

    except Exception as e:
        print(f"body取得エラー: {e}")

        # page_sourceで試す
        src = driver.page_source
        print(f"page_source長: {len(src)}文字")
        with open("kuji_debug.html", "w", encoding="utf-8") as f:
            f.write(src)
        print("kuji_debug.html 保存完了")

finally:
    input("\nEnterで終了...")
    driver.quit()
