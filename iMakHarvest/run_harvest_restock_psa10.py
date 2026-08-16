"""run_harvest_restock_psa10 - eBay で売れた PSA10 カードの「別個体」をメルカリで探す.

2026-08-17 新設 (user 依頼「売れた商品の補充」、 PSA10 から着手)。

売れた = 需要が証明されたカード。 PSA10 は 1 点ものなので同じ現物は買えないが、
**同じカードの別個体**を仕入れれば出し直せる。

流れ:
  ① eBay の注文一覧 (getOrders) で 売れた出品を取る
  ② その出品の Item Specifics (GetItem) で どのカードか確定する
     ★売れた行は HIGH シートに残らない (実測 30件中4件) ので eBay 側を SSOT にする
  ③ カード番号でメルカリを検索 (英語のカード名では日本語の出品は引けない)
  ④ 見つかった出品の写真から Vision でスラブラベルを読む
  ⑤ ラベルと eBay の Item Specifics を突合 (どちらも英字) して **同じカード**を確認
     売れた個体と同じ cert は除外 (= 同じ現物は買えない)
  ⑥ 中間スプシ mercari_restock_psa10 に出す

使い方:
  python run_harvest_restock_psa10.py --days 90 --dry-run       # 確認
  python run_harvest_restock_psa10.py --days 90                 # 中間スプシに書込
  python run_harvest_restock_psa10.py --days 90 --max-cards 3   # 少数で試す
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from scrapers import ebay_sold  # noqa: E402
from scrapers import mercari_item_detail  # noqa: E402
from scrapers import mercari_search as MSch  # noqa: E402
from scrapers import mercari_seller as MS  # noqa: E402
from scrapers import psa_cert  # noqa: E402
from scrapers import psa_restock  # noqa: E402
from scrapers import psa_slab_vision  # noqa: E402

DUMP_DIR = ROOT / "debug"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass


def _log(m: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


def collect_sold_cards(days: int, max_cards: int) -> list[dict]:
    """①② 売れた出品 → PSA10 カードの identity 一覧."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)
             ).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    sold = ebay_sold.fetch_sold_items(since)
    _log(f"売れた出品: {len(sold)} 件 (直近 {days} 日)")

    keys = ebay_sold._load_keys()
    cards, skipped = [], {"not_psa10": 0, "fetch_fail": 0}
    for s in sold:
        got = ebay_sold.fetch_item_specifics(s["item_id"], keys=keys)
        if not got["ok"]:
            skipped["fetch_fail"] += 1
            continue
        if not psa_restock.is_psa10_card(got["specifics"]):
            skipped["not_psa10"] += 1
            continue
        ident = psa_restock.to_card_identity(got["specifics"], got["title"])
        ident["sold_item_id"] = s["item_id"]
        ident["sold_at"] = s["sold_at"]
        ident["sold_cert"] = (got["specifics"].get("Certification Number") or "").strip()
        cards.append(ident)
        time.sleep(0.5)
    _log(f"PSA10 カード: {len(cards)} 件 / 対象外={skipped}")
    if max_cards:
        cards = cards[:max_cards]
        _log(f"上限 {max_cards} 件に制限")
    return cards


def find_replacements(cards: list[dict], args) -> list[dict]:
    """③〜⑤ カードごとにメルカリを探して 同一カードの別個体を拾う."""
    driver = MS.create_anonymous_driver(headless=False)  # メルカリは非 headless 必須
    found = []
    try:
        for n, card in enumerate(cards, 1):
            kws = psa_restock.build_keywords(card)
            if not kws:
                _log(f"[{n}/{len(cards)}] 番号が無く探せない: {card['ebay_title'][:40]}")
                continue
            _log(f"[{n}/{len(cards)}] {card['card_name']} {card['card_number']} "
                 f"({card['set_name'][:24]}) ← {kws}")

            collected = MSch.collect_multi_keyword_urls(
                kws, driver, price_min=args.price_min, price_max=args.price_max,
                cap_per_keyword=args.cap_per_keyword,
            )
            urls = collected["urls"][:args.max_details] if args.max_details \
                else collected["urls"]
            rej = {"sold": 0, "seller": 0, "fetch_fail": 0, "no_image": 0,
                   "vision_error": 0, "cert_unreadable": 0, "same_individual": 0,
                   "other_card": 0}

            for url in urls:
                detail = mercari_item_detail.fetch_detail(driver, url)
                if not detail:
                    rej["fetch_fail"] += 1
                    continue
                if not detail.get("in_stock"):
                    rej["sold"] += 1
                    continue
                q = MSch.extract_seller_quality(driver)
                if not MSch.passes_seller_filter(
                        q, min_rating_count=args.min_rating,
                        require_identity=not args.no_identity):
                    rej["seller"] += 1
                    continue
                images = [u for u in (detail.get("image_urls") or [])
                          if u.startswith("http")]
                if not images:
                    rej["no_image"] += 1
                    continue

                vision = psa_slab_vision.read_slab(images)
                if vision.get("error"):
                    rej["vision_error"] += 1
                    continue
                gate = psa_cert.local_gate(vision, detail.get("title") or "")
                if not gate["ok"]:
                    rej["cert_unreadable"] += 1
                    continue
                if psa_restock.is_same_individual(card["sold_cert"], vision["cert"]):
                    # 売れた現物そのもの = 買えない
                    rej["same_individual"] += 1
                    continue

                # 同じカードか: ラベル (英字) と eBay Item Specifics (英字) を突合
                m = psa_cert.match_signals(vision, psa_restock.to_match_info(card))
                if m["count"] < args.min_signals:
                    rej["other_card"] += 1
                    continue

                found.append({
                    "url": url, "title": detail.get("title"),
                    "condition": detail.get("condition"),
                    "price_jpy": detail.get("price_jpy"),
                    "image_urls": images, "description": detail.get("description"),
                    "cert": vision["cert"], "vision": vision,
                    "match_signals": m["signals"],
                    "sold_item_id": card["sold_item_id"],
                    "sold_at": card["sold_at"],
                    "card_name": card["card_name"],
                    "card_number": card["card_number"],
                })
                _log(f"    ○ cert={vision['cert']} ¥{detail.get('price_jpy')} "
                     f"({'/'.join(m['signals'])}) {url}")
                time.sleep(1.0)
            _log(f"    収集{len(urls)} → 候補{len([f for f in found if f['sold_item_id'] == card['sold_item_id']])} / reject={rej}")
    finally:
        try:
            driver.quit()
        except Exception:
            pass
    return found


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=90, help="何日前までの注文を見るか")
    ap.add_argument("--max-cards", type=int, default=0, help="対象カード数の上限 (0=無制限)")
    ap.add_argument("--price-min", type=int, default=3000)
    ap.add_argument("--price-max", type=int, default=100000)
    ap.add_argument("--min-rating", type=int, default=100)
    ap.add_argument("--no-identity", action="store_true")
    ap.add_argument("--cap-per-keyword", type=int, default=40)
    ap.add_argument("--max-details", type=int, default=15,
                    help="1 カードあたりの詳細フェッチ上限 (0=無制限)")
    ap.add_argument("--min-signals", type=int, default=2,
                    help="同一カード判定に要求する一致系統数")
    ap.add_argument("--label", default="restock_psa10")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    cards = collect_sold_cards(args.days, args.max_cards)
    if not cards:
        _log("対象カード 0 件 → 終了")
        return 0

    found = find_replacements(cards, args)
    path = DUMP_DIR / f"restock_psa10_{datetime.now():%Y%m%dT%H%M%S}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"cards": cards, "found": found},
                               ensure_ascii=False, indent=2), encoding="utf-8")
    _log(f"[FILE] {path}")

    covered = {f["sold_item_id"] for f in found}
    _log(f"結果: 売れたカード {len(cards)} 件中 {len(covered)} 件に代替候補あり "
         f"(候補 {len(found)} 件)")
    for c in cards:
        if c["sold_item_id"] not in covered:
            _log(f"  ⚠️ 代替なし: {c['card_name']} {c['card_number']} ({c['set_name'][:28]})")

    if args.dry_run:
        _log("dry-run → 書込なし")
        return 0
    if not found:
        _log("0 件 → 書込なし")
        return 0

    from sheet_writer_mercari_search import append_mercari_search_items  # noqa: PLC0415
    items = [{
        "url": f["url"], "title": f.get("title"), "condition": f.get("condition"),
        "price_jpy": f.get("price_jpy"), "image_urls": f.get("image_urls"),
        "description": f.get("description"), "cert": f["cert"],
    } for f in found]
    _log(f"[SHEET] {append_mercari_search_items(items, label=args.label)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
