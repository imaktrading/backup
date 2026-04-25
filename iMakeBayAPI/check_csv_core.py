#!/usr/bin/env python3
"""
iMak Trading Japan - check_csv 共通ヘルパー (SSOT)
全プロジェクトのcheck_csv.pyから import される共有関数群。

共通化対象:
- eBay API (OAuth/Browse/Aspects)
- TOPセラー判定・価格統計
- CSVローダ (find_latest_csv, load_csv, load_cost_data)
- Claude API (Anthropicキー読込)
- 価格帯別TIERパラメータ

プロジェクト固有の項目（REQUIRED_SPECIFICS, BANNED_WORDS, build_search_query 等）は
各プロジェクトの check_csv.py 内に残す。
"""

import os
import csv
import json
import time
import glob
import base64
import requests

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
EBAY_KEYS_FILE = os.path.join(SCRIPT_DIR, "ebay keys.txt")

# 価格帯別TIERパラメータ (GATE判定パラメータ検討.xlsx確定値)
TIER_PARAMS = [
    (39,   0.25, 0.50),
    (60,   0.25, 0.50),
    (100,  0.20, 0.50),
    (200,  0.15, 0.50),
    (300,  0.10, 0.40),
    (400,  0.10, 0.25),
    (500,  0.10, 0.20),
    (600,  0.10, 0.15),
    (800,  0.10, 0.10),
    (9999, 0.10, 0.10),
]

TOP_SELLER_MIN_FEEDBACK = 500
TOP_SELLER_MIN_PERCENTAGE = 98.0


def get_tier_params(median_usd):
    for threshold, profit_target, gap_limit in TIER_PARAMS:
        if median_usd <= threshold:
            return profit_target, gap_limit
    return 0.10, 0.10


# ===== eBay API =====
def load_ebay_keys():
    keys = {}
    try:
        with open(EBAY_KEYS_FILE, "r") as f:
            for line in f:
                line = line.strip()
                if "=" in line:
                    k, v = line.split("=", 1)
                    keys[k.strip()] = v.strip()
    except FileNotFoundError:
        print("  ⚠️ eBay APIキーが見つかりません。競合比較はスキップします。")
    return keys


def get_oauth_token(app_id, app_secret):
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


def search_ebay_active(token, keywords, category_ids, condition_id, limit=50):
    """Browse APIでアクティブ出品検索。Returns: (items_list, total_count)
    category_ids: 例 '183454' or '57988|52357|11450|15687'
    condition_id: 例 '2750' (Graded) or '3000' (Used)
    """
    url = "https://api.ebay.com/buy/browse/v1/item_summary/search"
    params = {
        "q": keywords,
        "filter": (
            "buyingOptions:{FIXED_PRICE},"
            f"conditionIds:{{{condition_id}}},"
            f"categoryIds:{{{category_ids}}}"
        ),
        "sort": "price",
        "limit": min(limit, 200),
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
        "Content-Type": "application/json",
    }
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=15)
        if resp.status_code != 200:
            return [], 0
        data = resp.json()
        return data.get("itemSummaries", []), data.get("total", 0)
    except Exception as e:
        print(f"  eBay API error: {e}")
        return [], 0


def fetch_top_seller_specs(token, items, max_items=3):
    """TOPセラーリスティングからItem Specifics取得・集約"""
    top_items = []
    for item in items:
        seller = item.get("seller", {})
        score = seller.get("feedbackScore", 0)
        try:
            pct = float(seller.get("feedbackPercentage", "0"))
        except (ValueError, TypeError):
            pct = 0
        if score >= TOP_SELLER_MIN_FEEDBACK and pct >= TOP_SELLER_MIN_PERCENTAGE:
            iid = item.get("itemId", "")
            if iid:
                top_items.append(iid)
        if len(top_items) >= max_items:
            break

    if not top_items:
        for item in items[:max_items]:
            iid = item.get("itemId", "")
            if iid:
                top_items.append(iid)

    all_specs = []
    for iid in top_items:
        try:
            url = f"https://api.ebay.com/buy/browse/v1/item/{iid}"
            headers = {
                "Authorization": f"Bearer {token}",
                "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
                "Content-Type": "application/json",
            }
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code != 200:
                continue
            data = resp.json()
            specs = {}
            for asp in data.get("localizedAspects", []):
                name = asp.get("name", "")
                value = asp.get("value", "")
                if name and value:
                    specs[name] = value
            if specs:
                all_specs.append(specs)
            time.sleep(0.3)
        except Exception:
            pass

    if not all_specs:
        return {}

    from collections import Counter
    merged = {}
    all_keys = set()
    for s in all_specs:
        all_keys.update(s.keys())
    for key in all_keys:
        values = [s[key] for s in all_specs if key in s]
        if values:
            merged[key] = Counter(values).most_common(1)[0][0]
    return merged


def fetch_ebay_market_median(keywords, category_ids, condition_id, limit=50, prefer_top_seller=True):
    """eBay Browse API から市場中央値を取得（pricing_engine.compute_listing_price 用）。

    既存の load_ebay_keys / get_oauth_token / search_ebay_active / classify_sellers を組合せた薄いブリッジ。
    Porter等の1点もの除外側（PRICE_CHECK_CONFIG.enabled=False）では呼ばない前提。

    Args:
      keywords: 検索キーワード（メーカー+型番のクリーン文字列推奨）
      category_ids: '261030' 等。複数なら '57988|52357'
      condition_id: '1000' / '3000' 等
      limit: API hit 件数上限
      prefer_top_seller: TOPセラー価格を優先（無ければ全体）

    Returns:
      (median_usd: float, hit_count: int)
      取得失敗・該当なしは (0.0, 0) — pricing_engine 側で NO_MEDIAN モードに落ちる
    """
    keys = load_ebay_keys()
    app_id = keys.get("AppID")
    app_secret = keys.get("AppSecret")
    if not app_id or not app_secret:
        return 0.0, 0
    if not keywords or not category_ids or not condition_id:
        return 0.0, 0
    try:
        token = get_oauth_token(app_id, app_secret)
    except Exception as e:
        print(f"  ebay OAuth 取得失敗 → median=0 で続行: {e}")
        return 0.0, 0
    items, _ = search_ebay_active(token, keywords, category_ids, condition_id, limit=limit)
    if not items:
        return 0.0, 0
    all_stats, top_stats = classify_sellers(items)
    stats = (top_stats if prefer_top_seller and top_stats else all_stats)
    if not stats:
        return 0.0, 0
    return float(stats["median"]), int(stats["count"])


def classify_sellers(items):
    """競合価格をTOP/全体で分類して統計を返す"""
    all_prices = []
    top_prices = []
    for item in items:
        try:
            price = float(item.get("price", {}).get("value", 0))
            if price <= 0:
                continue
        except (ValueError, TypeError):
            continue
        all_prices.append(price)
        seller = item.get("seller", {})
        score = seller.get("feedbackScore", 0)
        try:
            pct = float(seller.get("feedbackPercentage", "0"))
        except (ValueError, TypeError):
            pct = 0
        if score >= TOP_SELLER_MIN_FEEDBACK and pct >= TOP_SELLER_MIN_PERCENTAGE:
            top_prices.append(price)

    def stats(prices):
        if not prices:
            return None
        s = sorted(prices)
        return {
            "count": len(s),
            "min": s[0],
            "max": s[-1],
            "median": s[len(s) // 2],
            "avg": sum(s) / len(s),
        }
    return stats(all_prices), stats(top_prices)


# ===== CSV読込 =====
def find_latest_csv(patterns=None):
    if patterns is None:
        patterns = ["ebay_upload_*.csv", "data/ebay_upload_*.csv"]
    files = []
    for p in patterns:
        files.extend(glob.glob(p))
    files = [f for f in files if f.endswith(".csv")]
    if not files:
        return None
    return max(files, key=os.path.getmtime)


def load_csv(filepath):
    """CSV読込。Returns: (headers, rows, header_map)"""
    with open(filepath, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        headers = next(reader)
        header_map = {h: i for i, h in enumerate(headers)}
        rows = list(reader)
    return headers, rows, header_map


def load_cost_data(csv_path):
    """サイドカーJSON _cost.json から仕入値データ読込"""
    cost_file = csv_path.replace(".csv", "_cost.json")
    if os.path.exists(cost_file):
        with open(cost_file, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def get_col(row, col_name, header_map):
    """ヘッダー名から値取得 (header_mapを引数で渡す)"""
    idx = header_map.get(col_name)
    if idx is not None and idx < len(row):
        return str(row[idx]).strip()
    return ""


# ===== Anthropic =====
def load_anthropic_key(api_key_file):
    """API key.txtから読込"""
    try:
        with open(api_key_file, "r") as f:
            return f.read().strip()
    except FileNotFoundError:
        return None
