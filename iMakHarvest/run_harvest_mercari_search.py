"""run_harvest_mercari_search - メルカリ フリマ検索からポーター等を収集 (フィルタ付き).

2026-08-10 新設 (user 依頼)。
- 検索7クエリ (PORTER 組合せ) を匿名ドライバで収集 (mercari_search)。
- 検索URLフィルタ: 送料込み + 販売中 + 価格帯 (10000-30000)。
- 詳細フェッチで reject: 販売中でない / セラー評価数 < 100 / 本人確認未済。
- keep をスプシ or JSON (dry-run) に出力。

使い方:
  python run_harvest_mercari_search.py --dry-run --max-details 10 --cap-per-keyword 15   # POC
  python run_harvest_mercari_search.py --sheet-id <ID>                                    # 本番
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from scrapers import mercari_search as MSch  # noqa: E402
from scrapers import mercari_seller as MS  # noqa: E402
from scrapers import mercari_item_detail  # noqa: E402

# user 指定 (2026-08-10): PORTER 組合せで精度確保
DEFAULT_KEYWORDS = [
    "PORTER", "ポーター",
    "PORTER タンカー", "PORTER ヘルメットバッグ", "PORTER ボディバッグ",
    "PORTER ショルダーバッグ", "PORTER ビジネスバッグ",
]
DUMP_DIR = Path(r"c:\dev\iMak_data\catalog\_amazon_jp_dumps")


def _log(m: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--price-min", type=int, default=10000)
    ap.add_argument("--price-max", type=int, default=30000)
    ap.add_argument("--min-rating", type=int, default=100, help="セラー評価数の下限")
    ap.add_argument("--no-identity", action="store_true", help="本人確認済 要件を外す")
    ap.add_argument("--cap-per-keyword", type=int, default=150)
    ap.add_argument("--max-details", type=int, default=0, help="詳細フェッチ上限 (0=無制限、POC用)")
    ap.add_argument("--keywords", nargs="*", default=None, help="上書きキーワード")
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--manual", action="store_true",
                    help="フリマアシスト手動click で volume 突破 (非headless必須・キーワード毎に手動click)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--label", default="porter", help="中間スプシ tab suffix (= mercari_<label>)")
    args = ap.parse_args(argv)

    keywords = args.keywords or DEFAULT_KEYWORDS
    headless = args.headless and not args.manual  # manual は非headless 必須
    _log(f"開始: keywords={len(keywords)} 価格={args.price_min}-{args.price_max} "
         f"評価数>={args.min_rating} 本人確認={'不要' if args.no_identity else '必須'} "
         f"mode={'手動フリマアシスト' if args.manual else '自動scroll'}")
    if args.manual:
        _log("★手動モード: 各キーワードの検索画面でフリマアシスト「もっと見る」を click してください")

    driver = MS.create_anonymous_driver(headless=headless)
    kept, rej = [], {"sold": 0, "seller_rating": 0, "no_identity": 0, "fetch_fail": 0}
    try:
        collected = MSch.collect_multi_keyword_urls(
            keywords, driver, price_min=args.price_min, price_max=args.price_max,
            cap_per_keyword=args.cap_per_keyword, manual=args.manual,
            progress_callback=lambda n, m: _log(f"  収集 {m}"),
        )
        urls = collected["urls"]
        _log(f"収集: {len(urls)} URL (dedup後) / by_keyword={collected['by_keyword']}")
        if args.max_details:
            urls = urls[:args.max_details]
            _log(f"詳細フェッチ上限 {args.max_details} 件に制限 (POC)")

        for i, url in enumerate(urls, 1):
            detail = mercari_item_detail.fetch_detail(driver, url)
            if not detail:
                rej["fetch_fail"] += 1
                continue
            if not detail.get("in_stock"):
                rej["sold"] += 1
                continue
            q = MSch.extract_seller_quality(driver)  # 直前に開いた商品ページから
            if not MSch.passes_seller_filter(
                q, min_rating_count=args.min_rating,
                require_identity=not args.no_identity,
            ):
                if (q.get("rating_count") or 0) < args.min_rating:
                    rej["seller_rating"] += 1
                else:
                    rej["no_identity"] += 1
                continue
            item = dict(detail)
            item["url"] = url
            item["seller_rating_count"] = q.get("rating_count")
            item["seller_star"] = q.get("star")
            item["identity_verified"] = q.get("identity_verified")
            kept.append(item)
            if i % 10 == 0 or i == len(urls):
                _log(f"  詳細 {i}/{len(urls)} (keep={len(kept)} rej={rej})")
            time.sleep(1.0)
    finally:
        try:
            driver.quit()
        except Exception:
            pass

    _log(f"完了: 収集{len(collected['urls'])} → keep={len(kept)} / reject={rej}")

    DUMP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%dT%H%M%S")
    dump = DUMP_DIR / f"mercari_porter_{ts}.json"
    dump.write_text(json.dumps({"kept": kept, "reject": rej,
                                "by_keyword": collected["by_keyword"]},
                               ensure_ascii=False, indent=2), encoding="utf-8")
    _log(f"[FILE] JSON dump: {dump}")

    if args.dry_run:
        _log("dry-run → 中間スプシ書込なし")
        return 0
    if not kept:
        _log("keep 0 件 → 書込なし")
        return 0
    from sheet_writer_mercari_search import append_mercari_search_items  # noqa: PLC0415
    items = [{
        "url": k["url"], "title": k.get("title"), "condition": k.get("condition"),
        "price_jpy": k.get("price_jpy"), "image_urls": k.get("image_urls"),
        "description": k.get("description"), "size": k.get("size"),
        "color": k.get("color"),
    } for k in kept]
    res = append_mercari_search_items(items, label=args.label)
    _log(f"[SHEET] {res}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
