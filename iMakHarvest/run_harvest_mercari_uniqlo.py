"""run_harvest_mercari_uniqlo - メルカリから **ユニクロ UT / GU のコラボT** を集める.

2026-08-22 新設 (user 依頼「メルカリでユニクロのTシャツを抽出したい」)。
user 確定: **UT + GU のコラボT / 新品・未使用のみ**。

`run_harvest_mercari_search.py` (ポーター用) と同じ資産を使うが、 判定が別物なので
runner を分けた (あちらは `is_tanker` / `is_target_bag` に固定されている)。

落とす順:
  ① 検索URLで絞る … 販売中 / 送料込み / 価格帯 / **新品・未使用 (item_condition_id=1)**
  ② タイトルで落とす … ユニクロ or GU の T かつ **コラボ物**。まとめ売り・キッズ・難ありは捨てる
  ③ 商品ページで落とす … 売切れ / 状態が「新品、未使用」でない / セラー評価数・本人確認

使い方:
  python run_harvest_mercari_uniqlo.py --dry-run --max-details 10     # 下見
  python run_harvest_mercari_uniqlo.py                                 # 本番
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

import uniqlo_tee  # noqa: E402
from scrapers import mercari_item_detail  # noqa: E402
from scrapers import mercari_search as MSch  # noqa: E402
from scrapers import mercari_seller as MS  # noqa: E402

# UT/GU は「ブランド語 + IP名」で探すのが素直 (無地に埋もれない)。
# 語は増やしてよい。 減らすと取りこぼす。
DEFAULT_KEYWORDS = [
    "ユニクロ UT ワンピース Tシャツ",
    "ユニクロ UT ポケモン Tシャツ",
    "ユニクロ UT 鬼滅の刃 Tシャツ",
    "ユニクロ UT 呪術廻戦 Tシャツ",
    "ユニクロ UT ドラゴンボール Tシャツ",
    "ユニクロ UT スヌーピー Tシャツ",
    "ユニクロ UT ジブリ Tシャツ",
    "ユニクロ UT ディズニー Tシャツ",
    "GU コラボ Tシャツ アニメ",
    "ユニクロ UT コラボ Tシャツ 新品",
]
DUMP_DIR = ROOT / "debug"


def _log(m: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--price-min", type=int, default=1500)
    ap.add_argument("--price-max", type=int, default=12000)
    ap.add_argument("--min-rating", type=int, default=100, help="セラー評価数の下限")
    ap.add_argument("--no-identity", action="store_true", help="本人確認済 要件を外す")
    ap.add_argument("--cap-per-keyword", type=int, default=60)
    ap.add_argument("--max-details", type=int, default=0, help="詳細フェッチ上限 (0=無制限)")
    ap.add_argument("--keywords", nargs="*", default=None)
    ap.add_argument("--allow-used", action="store_true",
                    help="新品・未使用以外も通す (既定は 新品・未使用のみ)")
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--manual", action="store_true",
                    help="フリマアシスト『もっと見る』を手動 click して件数を伸ばす")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--label", default="uniqlo_ut", help="中間スプシ tab (= mercari_<label>)")
    args = ap.parse_args(argv)

    keywords = args.keywords or DEFAULT_KEYWORDS
    headless = args.headless and not args.manual
    conds = None if args.allow_used else [MSch.CONDITION_NEW]
    _log(f"開始: 語={len(keywords)} 価格={args.price_min}-{args.price_max} "
         f"状態={'新品・未使用のみ' if conds else '指定なし'} 評価数>={args.min_rating}")

    from scrapers._chrome_util import kill_chrome_for_profile
    killed = kill_chrome_for_profile(MS.CHROME_PROFILE_DIR_ANON)
    if killed:
        _log(f"前回の残留 chrome を {killed} 個 片付けました")

    driver = MS.create_anonymous_driver(headless=headless)
    kept: list[dict] = []
    rej = {"sold": 0, "not_uniqlo_tee": 0, "not_collab": 0, "not_new": 0,
           "seller_rating": 0, "no_identity": 0, "fetch_fail": 0}
    collected = {"urls": [], "by_keyword": {}}
    try:
        collected = MSch.collect_multi_keyword_urls(
            keywords, driver, price_min=args.price_min, price_max=args.price_max,
            cap_per_keyword=args.cap_per_keyword, manual=args.manual,
            item_condition_ids=conds, sleep_between_sec=8.0,
            progress_callback=lambda n, m: _log(f"  収集 {m}"),
        )
        urls = collected["urls"]
        _log(f"収集: {len(urls)} URL / by_keyword={collected['by_keyword']}")
        if args.max_details:
            urls = urls[:args.max_details]
            _log(f"詳細 {args.max_details} 件に制限")

        for i, url in enumerate(urls, 1):
            detail = mercari_item_detail.fetch_detail(driver, url)
            if not detail:
                rej["fetch_fail"] += 1
                continue
            if not detail.get("in_stock"):
                rej["sold"] += 1
                continue
            title = detail.get("title") or ""
            if not uniqlo_tee.is_uniqlo_tee(title):
                rej["not_uniqlo_tee"] += 1
                continue
            if not uniqlo_tee.is_collab(title):
                # 無地・エアリズムは海外で価格が付かない (user 確定 2026-08-22)
                rej["not_collab"] += 1
                continue
            if not args.allow_used and not uniqlo_tee.is_new_condition(
                    detail.get("condition") or ""):
                rej["not_new"] += 1
                continue
            q = MSch.extract_seller_quality(driver)
            if not MSch.passes_seller_filter(
                    q, min_rating_count=args.min_rating,
                    require_identity=not args.no_identity):
                key = ("seller_rating" if (q.get("rating_count") or 0) < args.min_rating
                       else "no_identity")
                rej[key] += 1
                continue
            item = dict(detail)
            item["url"] = url
            item["seller_rating_count"] = q.get("rating_count")
            kept.append(item)
            _log(f"  keep {len(kept)}件目 ¥{detail.get('price_jpy')} "
                 f"[{detail.get('condition')}] {title[:38]}")
            time.sleep(1.0)
    finally:
        try:
            driver.quit()
        except Exception:  # noqa: BLE001
            pass

    _log(f"完了: 収集{len(collected['urls'])} → keep={len(kept)} / 落とした内訳={rej}")
    DUMP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%dT%H%M%S")
    dump = DUMP_DIR / f"mercari_uniqlo_{ts}.json"
    dump.write_text(json.dumps({"kept": kept, "reject": rej,
                                "by_keyword": collected["by_keyword"]},
                               ensure_ascii=False, indent=2), encoding="utf-8")
    _log(f"[FILE] {dump}")

    if args.dry_run:
        _log("dry-run → 書込なし")
        return 0
    if not kept:
        return 0
    from sheet_writer_mercari_search import append_mercari_search_items  # noqa: PLC0415
    items = [{"url": k["url"], "title": k.get("title"), "condition": k.get("condition"),
              "price_jpy": k.get("price_jpy"), "image_urls": k.get("image_urls"),
              "description": k.get("description"), "size": k.get("size"),
              "color": k.get("color")} for k in kept]
    _log(f"[SHEET] {append_mercari_search_items(items, label=args.label)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
