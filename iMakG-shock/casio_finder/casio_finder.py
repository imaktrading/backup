#!/usr/bin/env python3
# iMak Trading Japan - CASIO未出品モデル発見スクリプト
# 使い方:
#   1. active_listings.csv（eBay出品中CSVをSeller Hubからダウンロード）を同フォルダに配置
#   2. python casio_finder.py を実行
#   3. unlisted_models.csv が出力される → AmazonでURLを確認してgshock_urls.txtに追加

import csv
import re
import time
from datetime import datetime
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# ===== 設定 =====
EBAY_CSV = "active_listings.csv"  # Seller HubからダウンロードしたeBay出品中CSV
OUTPUT_FILE = f"unlisted_models_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

# スクレイピング対象CASIOページ（シリーズ追加可能）
CASIO_SERIES_PAGES = [
    ("DW-6900", "https://www.casio.com/jp/watches/gshock/products/type/6900/all/"),
    ("DW-5600", "https://www.casio.com/jp/watches/gshock/products/type/5600/all/"),
    ("GA-2100", "https://www.casio.com/jp/watches/gshock/products/type/2100/all/"),
    ("GA-110",  "https://www.casio.com/jp/watches/gshock/products/type/110/all/"),
    ("GA-100",  "https://www.casio.com/jp/watches/gshock/products/type/100/all/"),
    ("GX-56",   "https://www.casio.com/jp/watches/gshock/products/type/gx-56/all/"),
]

def load_active_models(csv_path):
    """eBay出品中CSVからモデル番号を抽出"""
    active = set()
    try:
        with open(csv_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                title = row.get("Title", "")
                # モデル番号パターンを抽出（例：DW-6900UMS-1JF）
                models = re.findall(r'[A-Z]{2,4}-[0-9]{3,4}[A-Z0-9\-]*', title)
                for m in models:
                    # JF/JR末尾を除いた形で登録（統一のため）
                    normalized = re.sub(r'JF$|JR$', '', m)
                    active.add(normalized)
                    active.add(m)  # 元の形でも登録
    except FileNotFoundError:
        print(f"⚠️ {csv_path} が見つかりません")
    return active

def scrape_casio_series(driver, series_name, url):
    """CASIOシリーズページからモデル一覧を取得"""
    print(f"\n  スクレイピング中: {series_name}...")
    models = []
    try:
        driver.get(url)
        # 商品リストが読み込まれるまで待機
        time.sleep(5)
        
        # ページをスクロールして全商品を表示
        for _ in range(5):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(1)
        
        body = driver.find_element(By.TAG_NAME, "body").text
        
        # モデル番号を抽出
        # CASIOのモデル番号パターン（例：DW-6900UMS-1JF、GM-6900-1など）
        found = re.findall(r'[A-Z]{2,4}-[0-9]{3,4}[A-Z0-9\-]*(?:JF|JR)?', body)
        
        # 重複排除・フィルタリング
        seen = set()
        for m in found:
            # シリーズに関係するモデルのみ
            series_prefix = re.match(r'([A-Z]+-\d+)', series_name)
            if series_prefix and series_prefix.group(1).replace("-","") in m.replace("-",""):
                if m not in seen and len(m) > 5:
                    seen.add(m)
                    models.append(m)
        
        # ページ内のリンクからも抽出（product.XXX形式）
        links = driver.find_elements(By.TAG_NAME, "a")
        for link in links:
            href = link.get_attribute("href") or ""
            m = re.search(r'product\.([A-Z0-9\-]+)', href)
            if m:
                model = m.group(1)
                if model not in seen and len(model) > 5:
                    seen.add(model)
                    models.append(model)
        
        print(f"    → {len(models)}件取得")
    except Exception as e:
        print(f"    Error: {e}")
    
    return models

def check_new_flag(driver, model):
    """モデルページでNEWフラグ・限定フラグを確認"""
    url = f"https://www.casio.com/jp/watches/gshock/product.{model}/"
    try:
        driver.get(url)
        time.sleep(3)
        body = driver.find_element(By.TAG_NAME, "body").text
        is_new = "NEW" in body[:500] or "新発売" in body[:500]
        is_limited = any(kw in body[:1000] for kw in ["限定", "コラボ", "Anniversary", "周年"])
        price_match = re.search(r'￥\s*([\d,]+)', body)
        price_jpy = price_match.group(1).replace(",", "") if price_match else ""
        return is_new, is_limited, price_jpy
    except:
        return False, False, ""

def main():
    print("=== iMak Trading Japan - CASIO未出品モデル発見スクリプト ===\n")
    
    # 出品中モデル読み込み
    active_models = load_active_models(EBAY_CSV)
    print(f"eBay出品中モデル数: {len(active_models)}件\n")
    
    # Selenium起動
    options = uc.ChromeOptions()
    options.add_argument("--no-sandbox")
    driver = uc.Chrome(options=options, version_main=146)
    
    results = []
    
    for series_name, url in CASIO_SERIES_PAGES:
        casio_models = scrape_casio_series(driver, series_name, url)
        
        for model in casio_models:
            # 出品中と照合
            normalized = re.sub(r'JF$|JR$', '', model)
            is_active = model in active_models or normalized in active_models
            
            if not is_active:
                print(f"  未出品発見: {model} → 詳細確認中...", end="", flush=True)
                is_new, is_limited, price_jpy = check_new_flag(driver, model)
                casio_url = f"https://www.casio.com/jp/watches/gshock/product.{model}/"
                ebay_search = f"https://www.ebay.com/sch/i.html?_nkw={model.replace('-', '+')}&_sop=12"
                
                flags = []
                if is_new: flags.append("NEW")
                if is_limited: flags.append("限定")
                flag_str = "/".join(flags) if flags else "-"
                
                print(f" [{flag_str}] ¥{price_jpy}")
                
                results.append({
                    "シリーズ": series_name,
                    "モデル番号": model,
                    "フラグ": flag_str,
                    "CASIO希望価格(JPY)": price_jpy,
                    "CASIO URL": casio_url,
                    "eBay競合検索": ebay_search,
                })
    
    driver.quit()
    
    # CSV出力
    if results:
        with open(OUTPUT_FILE, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=["シリーズ", "モデル番号", "フラグ", "CASIO希望価格(JPY)", "CASIO URL", "eBay競合検索"])
            writer.writeheader()
            writer.writerows(results)
        
        print(f"\n=== 完了 ===")
        print(f"未出品モデル: {len(results)}件")
        print(f"出力ファイル: {OUTPUT_FILE}")
        print(f"\n【優先確認リスト】")
        for r in results:
            if r["フラグ"] != "-":
                print(f"  ⭐ {r['モデル番号']} [{r['フラグ']}] ¥{r['CASIO希望価格(JPY)']}")
        print(f"\n【その他】")
        for r in results:
            if r["フラグ"] == "-":
                print(f"  {r['モデル番号']} ¥{r['CASIO希望価格(JPY)']}")
    else:
        print("\n未出品モデルなし（全件出品済み）")
    
    input("\nEnterで終了...")

if __name__ == "__main__":
    main()
