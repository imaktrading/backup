"""picclick_watch_finder - PicClick 経由でライバルセラー listing の watcher 数取得.

5/15 ユーザー要望: eBay 公式 API では他店 watcher 非公開 → 3rd party PicClick から
HTML scrape で取得し、watch 多い listing を「実需要」シグナルとして使う。

PicClick (= picclick.com) は eBay 公開データを再加工する 3rd party。
URL: https://picclick.com/seller/<seller_id>
HTML 構造: `<div class="watchcount">N <span...> watchers</span></div>` + `<h3 title="...">`

使い方:
  python picclick_watch_finder.py pesa_japan
  python picclick_watch_finder.py pesa_japan --pages 3 --min-watch 5

出力:
  C:/dev/iMak_data/seller_analysis/<seller>_picclick_watch_<ts>.csv
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

# tile pattern: watchcount → h3 title → URL
_TILE_PATTERN = re.compile(
    r'watchcount">(\d+)\s*<span.*?<h3\s+title="([^"]+)".*?href="([^"]+)"',
    re.S,
)


def fetch_picclick_seller(seller_id: str, pages: int = 1, delay: float = 3.0) -> list[dict]:
    """PicClick の seller page から listing + watch count 抽出.

    pages: page 数 (= 1 page 約 77 件、6 page で 500 件目安)
    """
    items: list[dict] = []
    seen_ids = set()
    with scrape_session() as drv:
        for page in range(1, pages + 1):
            url = f"https://picclick.com/seller/{seller_id}"
            if page > 1:
                url += f"?page={page}"
            print(f"  📄 page {page}: {url}")
            drv.get(url)
            time.sleep(delay)
            html = drv.page_source
            page_items = 0
            for w, t, href in _TILE_PATTERN.findall(html):
                m = re.search(r"-(\d{10,15})\.html", href)
                eid = m.group(1) if m else ""
                if eid in seen_ids:
                    continue
                seen_ids.add(eid)
                items.append({
                    "watch_count": int(w),
                    "ebay_item_id": eid,
                    "title": t,
                    "picclick_url": href if href.startswith("http") else f"https://picclick.com{href}",
                })
                page_items += 1
            print(f"    → {page_items} 件取得 (累計 {len(items)})")
            if page_items == 0:
                print("    → 次 page に listing なし、終了")
                break
    return items


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("seller", help="eBay seller ID")
    parser.add_argument("--pages", type=int, default=3,
                        help="PicClick page 数 (default: 3 = 約 200 件)")
    parser.add_argument("--min-watch", type=int, default=1,
                        help="watch_count >= この値のみ保存 (default: 1)")
    args = parser.parse_args()

    print(f"=== PicClick watch finder: {args.seller} ===")
    print(f"  pages: {args.pages}  min watch: {args.min_watch}")

    items = fetch_picclick_seller(args.seller, pages=args.pages)
    # filter + sort
    items = [x for x in items if x["watch_count"] >= args.min_watch]
    items.sort(key=lambda x: -x["watch_count"])

    print(f"\n🎯 {len(items)} 件 (watch >= {args.min_watch})")
    print(f"\n=== TOP 15 (watch 降順) ===")
    for x in items[:15]:
        print(f"  watch {x['watch_count']:>4d}  eBay {x['ebay_item_id']}  {x['title'][:70]}")

    # 保存
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = os.path.join(OUTPUT_DIR, f"{args.seller}_picclick_watch_{ts}.csv")
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["watch_count", "ebay_item_id", "title",
                                            "picclick_url"],
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
