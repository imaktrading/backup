#!/usr/bin/env python3
# iMak Trading Japan - PSA Cert → eBay CSV 自動生成スクリプト
# 必要: pip install selenium undetected-chromedriver

import csv
import time
import re
from datetime import datetime, timedelta
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By

# ===== 設定 =====
CERTS_FILE = "certs.txt"
DESCRIPTION_FILE = "PSA10.txt"
DEFAULT_PRICE = 100.00
SCHEDULE_WEEKS = 2

PIC_URL = "https://raw.githubusercontent.com/imaktrading/imaktrading.github.io/main/999.png"
RETURN_POLICY = "No return"
PAYMENT_POLICY = "SALE"
LOCATION = "Osaka"

STORE_CATEGORIES = {
    "Gundam": 42145683010,
    "One Piece": 42142742010,
    "Dragon Ball": 42154739010,
    "Pokemon": 42054519010,
    "NIKKE": 42144249010,
    "Hololive": 42144254010,
}

SHIPPING_POLICIES = [
    (39, "<39"), (60, "40-60"), (100, "60-100"), (200, "100-200"),
    (300, "200-300"), (400, "300-400"), (500, "400-500"),
    (600, "500-600"), (800, "600-800"), (1000, "800-1000"),
]

RARITY_PATTERN = re.compile(
    r'\s+(LEGEND RARE\+|LEGEND RARE|RARE\+|RARE|COMMON\+|COMMON|UNCOMMON|PROMO|LR\+|LR|R\+|C\+)$',
    re.IGNORECASE
)

def get_shipping_policy(price):
    for threshold, policy in SHIPPING_POLICIES:
        if price <= threshold:
            return policy
    return "800-1000"

def get_schedule_time():
    future = datetime.utcnow() + timedelta(weeks=SCHEDULE_WEEKS)
    return future.strftime("%Y-%m-%d %H:%M:%S")

def get_store_category(franchise):
    for key, cat_id in STORE_CATEGORIES.items():
        if key.lower() in franchise.lower():
            return cat_id
    return 42054516010

def detect_game_info(brand):
    brand_upper = brand.upper()
    if "DUAL IMPACT" in brand_upper:
        return "Gundam CCG", "Dual Impact", "Gundam"
    elif "NEWTYPE RISING" in brand_upper:
        return "Gundam CCG", "Newtype Rising", "Gundam"
    elif "STEEL REQUIEM" in brand_upper:
        return "Gundam CCG", "Steel Requiem", "Gundam"
    elif "HEROIC BEGINNINGS" in brand_upper:
        return "Gundam CCG", "Heroic Beginnings", "Gundam"
    elif "WINGS OF ADVANCE" in brand_upper:
        return "Gundam CCG", "Wings of Advance", "Gundam"
    elif "ZEON" in brand_upper:
        return "Gundam CCG", "Zeon's Rush", "Gundam"
    elif "SEED STRIKE" in brand_upper:
        return "Gundam CCG", "SEED Strike", "Gundam"
    elif "IRON BLOOM" in brand_upper:
        return "Gundam CCG", "Iron Bloom", "Gundam"
    elif "EX BASE" in brand_upper or "PROMOS" in brand_upper:
        return "Gundam CCG", "Edition Beta Promos", "Gundam"
    elif "GUNDAM" in brand_upper:
        return "Gundam CCG", brand, "Gundam"
    elif "ONE PIECE" in brand_upper:
        return "One Piece Card Game", brand, "One Piece"
    elif "DRAGON BALL" in brand_upper:
        return "Dragon Ball Super Card Game", brand, "Dragon Ball"
    elif "POKEMON" in brand_upper:
        return "Pokemon", brand, "Pokemon"
    else:
        return brand, brand, brand

def build_title(game, set_name, card_number, subject):
    title = f"{game} {set_name} #{card_number} {subject} PSA 10 GEM MT Japanese"
    return title[:80]

def load_description():
    try:
        with open(DESCRIPTION_FILE, "r", encoding="utf-8") as f:
            return f.read()
    except:
        return "PSA graded card shipped from Japan. Grade and cert number are as listed."

def parse_psa_page(text):
    data = {}
    lines = [l.strip() for l in text.split('\n') if l.strip()]

    for i, line in enumerate(lines):
        # "2025 GUNDAM JAPANESE DUAL IMPACT #055 GUNDAM GUSION REBAKE" パターン
        match = re.search(r'^(.+?)\s+#(\w+)\s+(.+)$', line)
        if match and any(x in line.upper() for x in ['GUNDAM', 'ONE PIECE', 'DRAGON BALL', 'POKEMON']):
            brand_raw = match.group(1).strip()
            card_number = match.group(2).strip()
            subject_raw = match.group(3).strip()
            # レアリティを除去
            subject = RARITY_PATTERN.sub('', subject_raw).strip()
            # 年号をBrandから除去（例："2025 GUNDAM..." → "GUNDAM..."）
            brand = re.sub(r'^\d{4}\s+', '', brand_raw).strip()
            data['Brand'] = brand
            data['CardNumber'] = card_number  # 文字列のまま保持（006等）
            data['Subject'] = subject

        if line == '発行年' and i + 1 < len(lines):
            try:
                data['Year'] = int(lines[i + 1])
            except:
                data['Year'] = 2025

    return data

def get_psa_data(driver, cert_number):
    url = f"https://www.psacard.com/ja-JP/cert/{cert_number}/psa"
    try:
        driver.get(url)
        time.sleep(5)
        body = driver.find_element(By.TAG_NAME, "body").text
        data = parse_psa_page(body)
        if not data.get('Subject'):
            print(f"\n    [DEBUG] {body[:400]}")
        return data if data.get('Subject') else None
    except Exception as e:
        print(f"    Error: {e}")
        return None

def build_row(cert_number, price, data, description):
    subject = data.get('Subject', 'Unknown')
    card_number = data.get('CardNumber', '')
    brand = data.get('Brand', '')
    year = data.get('Year', 2025)

    card_number = str(card_number)  # ゼロ埋め保持
    game, set_name, franchise = detect_game_info(brand)
    title = build_title(game, set_name, card_number, subject)
    custom_label = f"{card_number}-PSA10" if card_number else f"PSA10-{cert_number}"
    store_cat_id = get_store_category(franchise)
    shipping = get_shipping_policy(price)

    return [
        "Add", 183454, title, PIC_URL, price, 2750,
        275010, 275020, cert_number,
        get_schedule_time(), custom_label, description,
        "FixedPrice", "GTC", 1, LOCATION, 1,
        shipping, RETURN_POLICY, PAYMENT_POLICY,
        game, set_name, "Unit", subject, subject, card_number,
        "", "", "Bandai", "Japanese", year, "Japan", franchise,
        "6+", "No", "No", "Card Stock", "Standard", "No",
        "Near Mint or Better", "10",
        "Professional Sports Authenticator (PSA)",
        store_cat_id,
    ]

def main():
    print("=== iMak Trading Japan - PSA → eBay CSV Generator ===\n")

    try:
        with open(CERTS_FILE, "r") as f:
            cert_numbers = [line.strip() for line in f if line.strip()]
    except FileNotFoundError:
        print(f"エラー: {CERTS_FILE} が見つかりません。")
        input("Enterで終了...")
        return

    print(f"{len(cert_numbers)}件を処理します。\n")

    options = uc.ChromeOptions()
    options.add_argument("--no-sandbox")
    driver = uc.Chrome(options=options, version_main=146)

    description = load_description()

    headers = [
        "*Action(SiteID=US|Country=JP|Currency=USD|Version=745|CC=UTF-8)",
        "*Category", "*Title", "PicURL", "*StartPrice", "ConditionID",
        "CD:Professional Grader - (ID: 27501)", "CD:Grade - (ID: 27502)",
        "CDA:Certification Number - (ID: 27503)", "ScheduleTime", "CustomLabel",
        "*Description", "*Format", "*Duration", "*Quantity", "*Location",
        "BestOfferEnabled", "ShippingProfileName", "ReturnProfileName", "PaymentProfileName",
        "C:Game", "C:Set", "C:Card Type", "C:Card Name", "C:Character", "C:Card Number",
        "C:Rarity", "C:Features", "C:Manufacturer", "C:Language", "C:Year Manufactured",
        "C:Country of Origin", "C:Franchise", "C:Age Level", "C:Autographed",
        "C:Vintage", "C:Material", "C:Card Size", "C:Customized",
        "C:Card Condition", "C:Grade", "C:Professional Grader", "StoreCategoryID",
    ]

    rows = [headers]
    errors = []

    for cert in cert_numbers:
        print(f"取得中: #{cert}...", end="", flush=True)
        data = get_psa_data(driver, cert)

        if data:
            subject = data.get('Subject', 'Unknown')
            card_number = data.get('CardNumber', '')
            print(f" → #{card_number} {subject} ✓")
            rows.append(build_row(cert, DEFAULT_PRICE, data, description))
        else:
            print(f" → 失敗")
            errors.append(cert)

    driver.quit()

    output_file = f"ebay_upload_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    with open(output_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, quoting=csv.QUOTE_NONNUMERIC)
        writer.writerows(rows)

    print(f"\n完了！出力: {output_file}")
    print(f"成功: {len(rows)-1}件 / 失敗: {len(errors)}件")
    if errors:
        print(f"失敗: {', '.join(errors)}")
    input("\nEnterで終了...")

if __name__ == "__main__":
    main()
