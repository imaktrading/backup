#!/usr/bin/env python3
"""
iMak Trading Japan - eBay Sold Listings Finder
Finding API廃止のため、Browse API（アクティブ出品）+ Sold Listingsページ解析の2段構成
"""

import csv
import re
import sys
import time
import requests
import base64
from datetime import datetime, timedelta
from urllib.parse import quote

try:
    import undetected_chromedriver as uc
    HAS_UC = True
except ImportError:
    HAS_UC = False

# --- 設定 ---
KEYS_FILE = "ebay keys.txt"

def load_keys():
    keys = {}
    with open(KEYS_FILE, "r") as f:
        for line in f:
            line = line.strip()
            if "=" in line:
                k, v = line.split("=", 1)
                keys[k.strip()] = v.strip()
    return keys

def get_oauth_token(app_id, app_secret):
    """Client Credentials Grant でアクセストークン取得"""
    credentials = base64.b64encode(f"{app_id}:{app_secret}".encode()).decode()
    resp = requests.post(
        "https://api.ebay.com/identity/v1/oauth2/token",
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Basic {credentials}",
        },
        data={
            "grant_type": "client_credentials",
            "scope": "https://api.ebay.com/oauth/api_scope",
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]

# ============================================================
# 1) Browse API: アクティブ出品の検索
# ============================================================
def search_browse_api(token, keywords, min_price=50, max_price=1000, limit=200):
    """Browse API で JP発送のアクティブ出品を検索"""
    url = "https://api.ebay.com/buy/browse/v1/item_summary/search"
    all_items = []
    offset = 0

    while offset < limit:
        page_limit = min(200, limit - offset)
        params = {
            "q": keywords,
            "filter": (
                f"price:[{min_price}..{max_price}],"
                "priceCurrency:USD,"
                "buyingOptions:{FIXED_PRICE},"
                "itemLocationCountry:JP"
            ),
            "sort": "-price",
            "limit": page_limit,
            "offset": offset,
        }
        headers = {
            "Authorization": f"Bearer {token}",
            "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
            "Content-Type": "application/json",
        }
        resp = requests.get(url, headers=headers, params=params, timeout=30)
        if resp.status_code != 200:
            print(f"  Browse API error {resp.status_code}: {resp.text[:200]}")
            break

        data = resp.json()
        items = data.get("itemSummaries", [])
        if not items:
            break

        all_items.extend(items)
        total = data.get("total", 0)
        print(f"  Active listings: {len(all_items)}/{total} fetched")

        if len(all_items) >= total or len(items) < page_limit:
            break
        offset += page_limit
        time.sleep(0.5)

    return all_items

def parse_browse_items(items):
    """Browse APIの結果をパース"""
    rows = []
    for item in items:
        price_val = item.get("price", {}).get("value", "0")
        rows.append({
            "source": "active",
            "title": item.get("title", ""),
            "price_usd": float(price_val),
            "currency": item.get("price", {}).get("currency", "USD"),
            "condition": item.get("condition", ""),
            "item_id": item.get("itemId", ""),
            "seller": item.get("seller", {}).get("username", ""),
            "location": item.get("itemLocation", {}).get("country", ""),
            "url": item.get("itemWebUrl", ""),
            "sold_date": "",
        })
    return rows

# ============================================================
# 2) eBay Sold Listingsページ解析（Web版）
# ============================================================
EBAY_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

def scrape_sold_listings(keywords, min_price=50, max_price=1000, max_pages=10):
    """eBay Sold Listingsページをスクレイピング（undetected-chromedriver使用）"""
    if not HAS_UC:
        print("  undetected-chromedriver not installed. pip install undetected-chromedriver")
        return []

    options = uc.ChromeOptions()
    options.add_argument("--no-sandbox")
    driver = uc.Chrome(options=options, version_main=146)
    all_items = []

    try:
        for page in range(1, max_pages + 1):
            url = (
                f"https://www.ebay.com/sch/i.html"
                f"?_nkw={quote(keywords)}"
                f"&_sop=12"           # Sort: End date recent first
                f"&LH_Complete=1"     # Completed listings
                f"&LH_Sold=1"         # Sold only
                f"&LH_BIN=1"          # Buy It Now only
                f"&_udlo={min_price}" # Min price
                f"&_udhi={max_price}" # Max price
                f"&_ipg=240"          # Items per page
                f"&_pgn={page}"
            )
            print(f"  Sold page {page}...", end="", flush=True)
            try:
                driver.get(url)
                time.sleep(4)
                html = driver.page_source
                items = parse_sold_html(html)
                if not items:
                    print(" no more items")
                    break

                all_items.extend(items)
                print(f" +{len(items)} items (total: {len(all_items)})")

                if len(all_items) >= 1000:
                    break
                time.sleep(2)
            except Exception as e:
                print(f" error: {e}")
                break
    finally:
        driver.quit()

    return all_items

def parse_sold_html(html):
    """eBay検索結果HTMLからSold情報を抽出"""
    items = []

    # s-item ブロックを分割
    blocks = re.split(r'<li[^>]*class="[^"]*s-item[^"]*"', html)

    for block in blocks[1:]:  # 最初のブロックはヘッダー
        # タイトル
        title_match = re.search(
            r'<div class="s-item__title"[^>]*>.*?<span[^>]*>(.*?)</span>',
            block, re.DOTALL
        )
        if not title_match:
            continue
        title = re.sub(r'<[^>]+>', '', title_match.group(1)).strip()
        if title in ("Shop on eBay", "Results Matching Fewer Words"):
            continue

        # 価格
        price_match = re.search(
            r'<span class="s-item__price"[^>]*>.*?\$([\d,]+\.?\d*)',
            block, re.DOTALL
        )
        if not price_match:
            continue
        price = float(price_match.group(1).replace(",", ""))

        # 日付
        date_match = re.search(r'Sold\s+(\w+\s+\d+,?\s*\d*)', block)
        sold_date = date_match.group(1).strip() if date_match else ""

        # URL
        url_match = re.search(r'href="(https://www\.ebay\.com/itm/[^"]+)"', block)
        item_url = url_match.group(1).split("?")[0] if url_match else ""

        # Item ID
        item_id = ""
        if item_url:
            id_match = re.search(r'/itm/(\d+)', item_url)
            if id_match:
                item_id = id_match.group(1)

        items.append({
            "source": "sold",
            "title": title,
            "price_usd": price,
            "currency": "USD",
            "condition": "",
            "item_id": item_id,
            "seller": "",
            "location": "",
            "url": item_url,
            "sold_date": sold_date,
        })

    return items

# ============================================================
# 分析 & CSV出力
# ============================================================
def analyze_and_output(keyword, sold_items, active_items):
    """分析してCSV出力"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_file = f"ebay_sold_{keyword.replace(' ', '_')}_{timestamp}.csv"

    all_items = sold_items + active_items

    # CSV出力
    fieldnames = ["source", "title", "price_usd", "currency", "condition",
                  "item_id", "seller", "location", "url", "sold_date"]
    with open(csv_file, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_items)

    # 分析
    sold_prices = [i["price_usd"] for i in sold_items if i["price_usd"] > 0]
    active_prices = [i["price_usd"] for i in active_items if i["price_usd"] > 0]

    print(f"\n{'='*60}")
    print(f"  Analysis: {keyword}")
    print(f"{'='*60}")

    if sold_prices:
        avg = sum(sold_prices) / len(sold_prices)
        median = sorted(sold_prices)[len(sold_prices) // 2]
        print(f"\n  [SOLD LISTINGS]")
        print(f"  Total sold:    {len(sold_prices)} items")
        print(f"  Price range:   ${min(sold_prices):.2f} - ${max(sold_prices):.2f}")
        print(f"  Average:       ${avg:.2f}")
        print(f"  Median:        ${median:.2f}")

        # 価格帯別
        brackets = [(50, 100), (100, 150), (150, 200), (200, 300), (300, 500), (500, 1000)]
        print(f"\n  Price distribution:")
        for lo, hi in brackets:
            count = sum(1 for p in sold_prices if lo <= p < hi)
            if count:
                bar = "#" * count
                print(f"    ${lo:>4}-${hi:<4}: {count:>3} {bar}")
    else:
        print("\n  [SOLD LISTINGS] No data found")

    if active_prices:
        avg_a = sum(active_prices) / len(active_prices)
        print(f"\n  [ACTIVE LISTINGS]")
        print(f"  Total active:  {len(active_prices)} items")
        print(f"  Price range:   ${min(active_prices):.2f} - ${max(active_prices):.2f}")
        print(f"  Average:       ${avg_a:.2f}")

    print(f"\n  CSV: {csv_file}")
    return csv_file, sold_prices

def profitability_check(sold_prices, cost_jpy, rate=150):
    """利益計算"""
    if not sold_prices:
        print("\n  Sold data unavailable - cannot calculate profitability")
        return

    cost_usd = cost_jpy / rate
    median = sorted(sold_prices)[len(sold_prices) // 2]
    avg = sum(sold_prices) / len(sold_prices)

    # eBay手数料 (Final Value Fee ~13.25%) + PayPal/Payment (~2.9%)
    fee_rate = 0.1625
    # 送料見積もり (JP→US)
    shipping_est = 15.0

    print(f"\n{'='*60}")
    print(f"  Profitability Check")
    print(f"{'='*60}")
    print(f"  Cost:          JPY {cost_jpy:,.0f} (${cost_usd:.2f} @ {rate} JPY/USD)")
    print(f"  Shipping est:  ${shipping_est:.2f}")
    print(f"  eBay fees:     {fee_rate*100:.1f}%")
    print(f"")

    for label, price in [("Median", median), ("Average", avg)]:
        fees = price * fee_rate
        profit = price - fees - shipping_est - cost_usd
        margin = (profit / price * 100) if price > 0 else 0
        status = "PROFIT" if profit > 0 else "LOSS"
        print(f"  [{label} ${price:.2f}]")
        print(f"    Revenue:  ${price:.2f}")
        print(f"    - Fees:   ${fees:.2f}")
        print(f"    - Ship:   ${shipping_est:.2f}")
        print(f"    - Cost:   ${cost_usd:.2f}")
        print(f"    = {status}: ${profit:.2f} (margin {margin:.1f}%)")
        print()

# ============================================================
# メイン
# ============================================================
def main():
    if len(sys.argv) < 2:
        keyword = input("Search keyword: ").strip()
    else:
        keyword = " ".join(sys.argv[1:])

    if not keyword:
        print("No keyword provided.")
        return

    cost_jpy = 8000  # デフォルト仕入れ価格
    min_price = 50
    max_price = 1000

    print(f"\n=== eBay Sold Finder: '{keyword}' ===")
    print(f"  Price range: ${min_price}-${max_price}, Location: JP, BIN only\n")

    # APIキー読み込み
    keys = load_keys()
    app_id = keys.get("AppID", "")
    app_secret = keys.get("AppSecret", "")

    # 1) Sold Listings (Web scrape)
    print("[1/2] Scraping Sold Listings...")
    sold_items = scrape_sold_listings(keyword, min_price, max_price)

    # 2) Browse API (Active listings)
    active_items = []
    if app_id and app_secret:
        print("\n[2/2] Browse API - Active Listings...")
        try:
            token = get_oauth_token(app_id, app_secret)
            print("  OAuth token OK")
            browse_raw = search_browse_api(token, keyword, min_price, max_price)
            active_items = parse_browse_items(browse_raw)
        except Exception as e:
            print(f"  Browse API failed: {e}")
    else:
        print("\n[2/2] Skipped (no API keys)")

    # 分析 & CSV
    csv_file, sold_prices = analyze_and_output(keyword, sold_items, active_items)

    # 利益判定
    profitability_check(sold_prices, cost_jpy)

    print(f"\nDone!")

if __name__ == "__main__":
    main()
