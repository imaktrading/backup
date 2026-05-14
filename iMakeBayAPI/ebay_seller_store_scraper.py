"""ebay_seller_store_scraper - ライバルセラーの listing を Browse API で取得.

5/15 Gemini 助言で Selenium 経路から Browse API 経路に変更。

実装ポイント:
- 既存 client_credentials (Browse API token) を流用
- filter=sellers:{seller_id} で seller-specific 取得
- X-EBAY-C-ENDUSERCTX: contextualLocation で US 配送先強制 (JP IP からの geo-block 回避)
- limit=200 で pagination

使い方:
  python ebay_seller_store_scraper.py pesa_japan
  python ebay_seller_store_scraper.py pesa_japan --max 1000
  python ebay_seller_store_scraper.py pesa_japan --max 1000 --details 5

出力:
  C:/dev/iMak_data/seller_analysis/<seller>_listings_<ts>.csv
  C:/dev/iMak_data/seller_analysis/<seller>_details_<ts>.csv (--details 指定時)
  C:/dev/iMak_data/seller_analysis/<seller>_summary_<ts>.json
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import datetime
from urllib.parse import quote

import requests

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
from check_csv_core import load_ebay_keys, get_oauth_token

OUTPUT_DIR = r"C:\dev\iMak_data\seller_analysis"
BROWSE_ENDPOINT = "https://api.ebay.com/buy/browse/v1/item_summary/search"


def resolve_seller_id(input_str: str) -> str:
    """seller_id (例: 'pesa_japan') / store URL / display 名 を実 username に解決.

    判定:
      - http で始まる → store URL → /str/<x> or /usr/<x> 抽出 → 必要なら HTML から実 user_id 取得
      - そのまま seller_id らしい (snake_case 等) → そのまま返す
    """
    import re
    s = input_str.strip()
    if s.startswith("http"):
        m = re.search(r"/(?:str|usr)/([^/?#]+)", s)
        if m:
            slug = m.group(1)
            # store URL の slug は表示名 (= 実 user_id と異なる場合あり、例: snahop → qbks_89)
            # 試行: store ページを scrape して _ssn=<実 username> を取得
            try:
                import time
                _here = os.path.dirname(os.path.abspath(__file__))
                if _here not in sys.path:
                    sys.path.insert(0, _here)
                from ebay_listing_scraper import scrape_session
                with scrape_session() as drv:
                    drv.get(f"https://www.ebay.com/str/{slug}")
                    time.sleep(6)
                    html = drv.page_source
                    matches = re.findall(r"_ssn=([a-zA-Z0-9._-]+)", html)
                    if matches:
                        real_id = list(set(matches))[0]
                        if real_id != slug:
                            print(f"  ✓ slug '{slug}' → real user_id '{real_id}'")
                        return real_id
            except Exception as e:
                print(f"  [WARN] real user_id 解決失敗: {e}、slug 使用")
            return slug
    return s


def search_seller_listings(token: str, seller_id: str,
                            max_total: int = 200,
                            marketplace: str = "EBAY_US",
                            ship_to_country: str = "US",
                            ship_to_zip: str = "10001") -> tuple[list[dict], int]:
    """Browse API で seller の listing 一覧を pagination 込み取得.

    Returns: (items, total_count)
    """
    items = []
    total_count = 0
    offset = 0
    page_size = 200  # Browse API 最大
    while offset < max_total:
        params = {
            "category_ids": "0",  # root category (= 全カテゴリ)、API 仕様で q/category_ids 必須
            "filter": f"sellers:{{{seller_id}}}",
            "limit": min(page_size, max_total - offset),
            "offset": offset,
        }
        ctx_value = f"contextualLocation=country={ship_to_country},zip={ship_to_zip}"
        headers = {
            "Authorization": f"Bearer {token}",
            "X-EBAY-C-MARKETPLACE-ID": marketplace,
            "X-EBAY-C-ENDUSERCTX": ctx_value,
            "Content-Type": "application/json",
        }
        try:
            resp = requests.get(BROWSE_ENDPOINT, headers=headers, params=params, timeout=20)
        except Exception as e:
            print(f"  [ERROR] request failed: {e}")
            break
        if resp.status_code != 200:
            print(f"  [ERROR] HTTP {resp.status_code}: {resp.text[:300]}")
            break
        data = resp.json()
        page_items = data.get("itemSummaries", []) or []
        items.extend(page_items)
        total_count = data.get("total", total_count)
        if not page_items or len(page_items) < page_size:
            break
        offset += len(page_items)
    return items, total_count


def _extract_item_id(api_id: str) -> str:
    """Browse API itemId 'v1|123456789012|0' から実 ItemID (12桁) を取得."""
    if not api_id:
        return ""
    parts = api_id.split("|")
    # parts = ['v1', '123456789012', '0'] のような構造、中間の数字部分が ItemID
    for p in parts:
        if p.isdigit() and len(p) >= 10:
            return p
    return parts[-1]


def normalize_listing(item: dict) -> dict:
    """Browse API レスポンスを CSV 互換 dict に正規化."""
    price = item.get("price") or {}
    seller = item.get("seller") or {}
    img = (item.get("image") or {}).get("imageUrl", "")
    return {
        "item_id": _extract_item_id(item.get("itemId", "")),
        "title": item.get("title", ""),
        "price_value": price.get("value", ""),
        "price_currency": price.get("currency", ""),
        "condition": item.get("condition", ""),
        "category_path": " > ".join(c.get("categoryName", "") for c in item.get("categories", [])),
        "leaf_category_id": item.get("leafCategoryIds", [""])[0] if item.get("leafCategoryIds") else "",
        "seller_username": seller.get("username", ""),
        "seller_feedback_pct": seller.get("feedbackPercentage", ""),
        "seller_feedback_score": seller.get("feedbackScore", ""),
        "buying_options": ",".join(item.get("buyingOptions", [])),
        "image_url": img,
        "item_web_url": item.get("itemWebUrl", ""),
        "shipping_type": (item.get("shippingOptions", [{}])[0].get("shippingCostType", "") if item.get("shippingOptions") else ""),
        "shipping_cost": (item.get("shippingOptions", [{}])[0].get("shippingCost", {}).get("value", "") if item.get("shippingOptions") else ""),
        "watch_count": item.get("watchCount", ""),
        "item_location_country": (item.get("itemLocation") or {}).get("country", ""),
    }


def fetch_listing_detail_via_api(token: str, item_id: str,
                                   marketplace: str = "EBAY_US",
                                   ship_to_country: str = "US",
                                   ship_to_zip: str = "10001") -> dict:
    """Browse API getItem で listing 詳細 (Item Specifics 含む) 取得."""
    if "|" not in item_id and not item_id.startswith("v1|"):
        api_id = f"v1|{item_id}|0"
    else:
        api_id = item_id
    url = f"https://api.ebay.com/buy/browse/v1/item/{quote(api_id, safe='|')}"
    headers = {
        "Authorization": f"Bearer {token}",
        "X-EBAY-C-MARKETPLACE-ID": marketplace,
        "X-EBAY-C-ENDUSERCTX": f"contextualLocation=country={ship_to_country},zip={ship_to_zip}",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=20)
        if resp.status_code != 200:
            return {"item_id": item_id, "error": f"HTTP {resp.status_code}"}
        return resp.json()
    except Exception as e:
        return {"item_id": item_id, "error": str(e)}


def save_results(seller_id: str, listings: list[dict], details: list[dict],
                  total_count: int) -> tuple[str, str, str]:
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    # listings CSV
    list_path = os.path.join(OUTPUT_DIR, f"{seller_id}_listings_{ts}.csv")
    if listings:
        cols = list(listings[0].keys())
        with open(list_path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=cols, quoting=csv.QUOTE_NONNUMERIC,
                                extrasaction="ignore")
            w.writeheader()
            w.writerows(listings)

    # details CSV (Item Specifics 含む)
    details_path = ""
    if details:
        details_path = os.path.join(OUTPUT_DIR, f"{seller_id}_details_{ts}.csv")
        with open(details_path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=[
                "item_id", "title", "price_value", "price_currency",
                "condition", "category_path", "leaf_category_id",
                "description_excerpt", "specifics_json", "image_count",
                "item_web_url", "error",
            ], quoting=csv.QUOTE_NONNUMERIC, extrasaction="ignore")
            w.writeheader()
            for d in details:
                if d.get("error"):
                    w.writerow({"item_id": d.get("item_id", ""), "error": d["error"]})
                    continue
                price = d.get("price") or {}
                specs = {a.get("name", ""): a.get("value", "")
                          for a in d.get("localizedAspects") or []}
                w.writerow({
                    "item_id": _extract_item_id(d.get("itemId", "")),
                    "title": d.get("title", ""),
                    "price_value": price.get("value", ""),
                    "price_currency": price.get("currency", ""),
                    "condition": d.get("condition", ""),
                    "category_path": (d.get("categoryPath") or "").replace("|", " > "),
                    "leaf_category_id": d.get("categoryId", ""),
                    "description_excerpt": (d.get("description") or "")[:500].replace("\n", " "),
                    "specifics_json": json.dumps(specs, ensure_ascii=False),
                    "image_count": len(d.get("additionalImages") or []) + (1 if d.get("image") else 0),
                    "item_web_url": d.get("itemWebUrl", ""),
                })

    # summary JSON
    summary_path = os.path.join(OUTPUT_DIR, f"{seller_id}_summary_{ts}.json")
    summary = {
        "seller_id": seller_id,
        "total_count_api": total_count,
        "listings_fetched": len(listings),
        "details_fetched": len(details),
        "timestamp": ts,
    }
    if listings:
        prices = [float(x["price_value"]) for x in listings
                  if x.get("price_value") and str(x["price_value"]).replace(".", "").isdigit()]
        if prices:
            prices.sort()
            mid = len(prices) // 2
            summary["price_stats"] = {
                "count": len(prices), "min": min(prices), "max": max(prices),
                "median": prices[mid] if len(prices) % 2 else (prices[mid - 1] + prices[mid]) / 2,
                "avg": sum(prices) / len(prices),
            }
        from collections import Counter
        cat_counter = Counter(x.get("category_path", "").split(" > ")[-1] for x in listings)
        summary["top_categories"] = cat_counter.most_common(10)
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    return list_path, details_path, summary_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("seller", help="eBay seller ID (例: pesa_japan)")
    parser.add_argument("--max", type=int, default=200,
                        help="取得 listing 上限 (default: 200, max: 10000)")
    parser.add_argument("--details", type=int, default=0,
                        help="上位 N 件の Item Specifics 詳細も取得")
    parser.add_argument("--marketplace", default="EBAY_US",
                        help="marketplace ID (default: EBAY_US)")
    parser.add_argument("--ship-to", default="US",
                        help="ship_to country code (default: US)")
    parser.add_argument("--ship-zip", default="10001",
                        help="ship_to zip code (default: 10001 NYC)")
    parser.add_argument("--with-watch", action="store_true",
                        help="PicClick から watch 数を取得して watch_count 列を埋める")
    parser.add_argument("--watch-pages", type=int, default=3,
                        help="PicClick 取得 page 数 (default: 3)")
    args = parser.parse_args()

    # URL 入力対応: store URL / display name → 実 user_id 解決
    seller_id = resolve_seller_id(args.seller)
    args.seller = seller_id
    print(f"=== eBay seller listings via Browse API ===")
    print(f"  seller: {seller_id}")
    print(f"  max: {args.max}  details: {args.details}")
    print(f"  marketplace: {args.marketplace}  ship_to: {args.ship_to}/{args.ship_zip}")

    keys = load_ebay_keys()
    if not keys.get("AppID") or not keys.get("AppSecret"):
        print("[ERROR] eBay AppID/AppSecret が見つかりません")
        return 1

    print("\n📡 OAuth token 取得中...")
    token = get_oauth_token(keys["AppID"], keys["AppSecret"])
    print("  ✓ token 取得済")

    print(f"\n🔍 seller listings 検索中 (filter=sellers:{{{args.seller}}})...")
    raw_items, total = search_seller_listings(
        token, args.seller, max_total=args.max,
        marketplace=args.marketplace,
        ship_to_country=args.ship_to, ship_to_zip=args.ship_zip,
    )
    print(f"  ✓ {len(raw_items)} 件取得 (API 報告 total={total})")

    listings = [normalize_listing(x) for x in raw_items]

    # PicClick から watch 数 + URL を取得して merge
    if args.with_watch and listings:
        print(f"\n👀 PicClick から watch 数 + URL 取得中 (pages={args.watch_pages})...")
        try:
            from picclick_watch_finder import fetch_picclick_seller
            picclick_items = fetch_picclick_seller(args.seller, pages=args.watch_pages)
            pic_map = {x["ebay_item_id"]: x for x in picclick_items}
            n_filled = 0
            for L in listings:
                p = pic_map.get(L["item_id"])
                if p is not None:
                    L["watch_count"] = p["watch_count"]
                    L["picclick_url"] = p["picclick_url"]
                    n_filled += 1
                else:
                    L["picclick_url"] = ""
            print(f"  ✓ {n_filled}/{len(listings)} 件に watch + PicClick URL を反映")
        except Exception as e:
            print(f"  [WARN] PicClick 取得失敗: {e}")

    # 詳細取得
    details = []
    if args.details > 0:
        print(f"\n📦 上位 {args.details} 件の詳細取得中...")
        for i, item in enumerate(listings[:args.details], start=1):
            iid = item["item_id"]
            print(f"  [{i}/{args.details}] {iid} {item['title'][:60]}")
            d = fetch_listing_detail_via_api(
                token, iid,
                marketplace=args.marketplace,
                ship_to_country=args.ship_to, ship_to_zip=args.ship_zip,
            )
            details.append(d)

    list_path, details_path, summary_path = save_results(
        args.seller, listings, details, total,
    )

    # サマリー出力
    print(f"\n📊 サマリー:")
    if listings:
        prices = [float(x["price_value"]) for x in listings
                  if x.get("price_value") and str(x["price_value"]).replace(".", "").isdigit()]
        if prices:
            print(f"  価格 (USD): min ${min(prices):.2f} / median ${sorted(prices)[len(prices)//2]:.2f} / max ${max(prices):.2f}")
        from collections import Counter
        cats = Counter(x.get("category_path", "").split(" > ")[-1] for x in listings)
        print(f"  TOP カテゴリ:")
        for c, n in cats.most_common(5):
            print(f"    {c}: {n}")

    print(f"\n💾 listings: {list_path}")
    if details_path:
        print(f"💾 details:  {details_path}")
    print(f"💾 summary:  {summary_path}")
    try:
        os.startfile(list_path)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
