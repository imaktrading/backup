"""watchcount_trending_finder - WatchCount.com からカテゴリ別 trending listing 取得.

5/15 ユーザー要望: WatchCount で sold 数も取得可能と判明、PicClick (watch のみ、
seller 単位) を補完する形で カテゴリ全体の trending を発掘するツール。

WatchCount 特徴:
- sold + watch + bid の 3 指標
- カテゴリ単位 ranking (= seller filter なし)
- 15 秒 anti-bot validation 待機必要
- HTML scrape (公開 API なし)

使い方:
  python watchcount_trending_finder.py --category-id 183454 --category-name trading-cards
  python watchcount_trending_finder.py --category-id 31387 --category-name wristwatches

代表的 eBay category ID:
  183454 = Trading Cards (CCG)
  31387  = Wristwatches
  220    = Toys & Hobbies (Action Figures)
  46336  = Reels (Fishing)
  259105 = Anime Trading Cards

出力:
  C:/dev/iMak_data/seller_analysis/watchcount_<cat>_<ts>.csv
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import time
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
from ebay_listing_scraper import scrape_session

OUTPUT_DIR = r"C:\dev\iMak_data\seller_analysis"


def fetch_watchcount(category_name: str, category_id: str,
                      site: str = "EBAY_US", wait_seconds: int = 15) -> list[dict]:
    """WatchCount.com の カテゴリページから listing 抽出.

    URL 形式: https://www.watchcount.com/live/-/<category-name>_<category-id>/all?site=EBAY_US
    """
    url = f"https://www.watchcount.com/live/-/{category_name}_{category_id}/all?site={site}"
    print(f"  📄 {url}")
    items = []
    with scrape_session() as drv:
        drv.get(url)
        time.sleep(wait_seconds)  # anti-bot validation 突破
        html = drv.page_source
        if "Validating request" in html or len(html) < 50000:
            print(f"  [WARN] anti-bot validation 失敗 (html size {len(html)})")
            return items
        # parse: 各 tile から title / price / watch / sold / ebay URL
        # WatchCount の tile pattern: 構造未確定、複数 fallback で抽出
        # tile section delimiter
        items = _parse_watchcount_html(html)
    print(f"  → {len(items)} 件取得")
    return items


def _parse_watchcount_html(html: str) -> list[dict]:
    """WatchCount HTML から listing 抽出 (item-content block 単位).

    実 HTML 構造 (5/15 確認):
      `item=<id>` URL pattern
      Watchers: <N> * Sold: <N> * Average: <X.X> sold per day
    """
    items = []
    # item-content block を抜き出して per-item 解析
    blocks = re.split(r'<div class="col-auto item-content">', html)
    seen = set()
    for block in blocks[1:]:  # 1 番目は header
        # eBay item ID 抽出 (URL pattern: item=<id> or itm/<id>)
        m_id = re.search(r"item[/=](\d{10,15})", block)
        if not m_id:
            continue
        ebay_id = m_id.group(1)
        if ebay_id in seen:
            continue
        seen.add(ebay_id)
        # 各種 metric (Watchers / Sold / Average / 価格)
        m_watch = re.search(r"Watchers?:\s*([\d,]+)", block)
        m_sold = re.search(r"Sold:\s*([\d,]+)", block)
        m_avg = re.search(r"Average:\s*([\d.]+)\s*sold per day", block)
        m_price = re.search(r"(?:US\s*)?\$([\d,]+(?:\.\d{2})?)", block)
        # title (eBay 商品タイトル)
        m_title = re.search(r'>([^<]{20,200})</a>', block)
        title = m_title.group(1).strip() if m_title else ""
        # URL クリーン (= eBay 直接 link)
        items.append({
            "ebay_item_id": ebay_id,
            "title": title,
            "watch_count": int(m_watch.group(1).replace(",", "")) if m_watch else 0,
            "sold_count": int(m_sold.group(1).replace(",", "")) if m_sold else 0,
            "sold_per_day": float(m_avg.group(1)) if m_avg else 0.0,
            "bid_count": 0,
            "price_usd": m_price.group(1).replace(",", "") if m_price else "",
            "ebay_url": f"https://www.ebay.com/itm/{ebay_id}",
        })
    return items


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--category-id", required=True,
                        help="eBay category ID (例: 183454=Trading Cards)")
    parser.add_argument("--category-name", required=True,
                        help="WatchCount URL slug (例: trading-cards / wristwatches)")
    parser.add_argument("--site", default="EBAY_US",
                        help="eBay site (default: EBAY_US)")
    parser.add_argument("--wait", type=int, default=15,
                        help="anti-bot validation 待機秒 (default: 15)")
    parser.add_argument("--sort-by", choices=["sold", "watch", "bid"], default="sold",
                        help="出力ソート基準 (default: sold)")
    args = parser.parse_args()

    print(f"=== WatchCount trending finder ===")
    print(f"  category: {args.category_name} ({args.category_id})")
    print(f"  site: {args.site}")
    print(f"  sort by: {args.sort_by}")

    items = fetch_watchcount(args.category_name, args.category_id,
                              site=args.site, wait_seconds=args.wait)
    if not items:
        print("[ERROR] 0 件、URL や category_name 確認")
        return 1

    # ソート
    sort_key = f"{args.sort_by}_count"
    items.sort(key=lambda x: -x.get(sort_key, 0))

    print(f"\n🎯 TOP 15 (by {args.sort_by})")
    for x in items[:15]:
        print(f"  watch {x['watch_count']:>4d}  sold {x['sold_count']:>4d}  ${x['price_usd']:>8s}  {x['title'][:65]}")

    # 保存
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_cat = re.sub(r"[^A-Za-z0-9_-]", "_", args.category_name)[:40]
    out = os.path.join(OUTPUT_DIR, f"watchcount_{safe_cat}_{args.category_id}_{ts}.csv")
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["watch_count", "sold_count", "bid_count",
                                            "price_usd", "title", "ebay_item_id",
                                            "ebay_url"],
                            quoting=csv.QUOTE_NONNUMERIC, extrasaction="ignore")
        w.writeheader()
        w.writerows(items)
    print(f"\n💾 {out}")
    try:
        os.startfile(out)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
