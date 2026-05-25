"""Yu-Gi-Oh! TCG → iMakCatalog scraper.

設計 (2026-05-26):
  - data source: ygoprodeck.com v7 API (= 公式 Konami DB 同期、 fan-maintained だが精度高)
  - 1 endpoint で 全 14,371 cards 取得可能 (大量 JSON)
  - language=ja で ja+en 同時取得 (= name_jp + name_en 1 call)

catalog schema:
  - category = 'yugioh_tcg'
  - product_id = '<Konami official ID>' (例: '89631139' = Blue-Eyes White Dragon)
  - name = ja name
  - name_jp = ja name
  - name_en = en name
  - set_name = card_sets[最新] の set_name (= 主要 set)
  - specs = {type / race / attribute / level / atk / def / archetype / desc /
              banlist_tcg / banlist_ocg / card_sets_count / etc}
  - images = [card_images[0].image_url]
  - source = 'ygoprodeck'
  - source_url = ygoprodeck_url

実行:
  python iMakCatalog/scrapers/yugioh_tcg.py --update    # 差分のみ
  python iMakCatalog/scrapers/yugioh_tcg.py --full      # 全件上書き
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Optional

import requests

_CATALOG_ROOT = Path(__file__).resolve().parent.parent
if str(_CATALOG_ROOT) not in sys.path:
    sys.path.insert(0, str(_CATALOG_ROOT))
import api  # type: ignore  # noqa: E402

CATEGORY = "yugioh_tcg"
SOURCE = "ygoprodeck"
API_BASE = "https://db.ygoprodeck.com/api/v7/cardinfo.php"


def fetch_all_cards(language: str = "ja") -> list[dict]:
    """全 cards を 1 query で取得.

    Args:
        language: 'ja' で ja+en 併取得、 'en' で en のみ、 省略で en のみ.

    Returns:
        list of card dict.
    """
    params = {"language": language} if language else {}
    print(f"  fetching all cards (language={language!r}) ...")
    r = requests.get(API_BASE, params=params,
                      headers={"User-Agent": "Mozilla/5.0"}, timeout=60)
    r.raise_for_status()
    data = r.json()
    cards = data.get("data", [])
    print(f"  fetched: {len(cards):,} cards")
    return cards


def build_specs(card: dict) -> dict:
    """API card dict → catalog specs JSON 用 dict."""
    out: dict = {}
    # Common
    for k in ("type", "race", "frameType", "humanReadableCardType", "archetype",
              "attribute", "level", "atk", "def", "scale", "linkval", "linkmarkers",
              "desc"):
        if k in card and card[k] not in (None, ""):
            out[k] = card[k]
    # Banlist
    bl = card.get("banlist_info") or {}
    if bl:
        if "ban_tcg" in bl:
            out["banlist_tcg"] = bl["ban_tcg"]
        if "ban_ocg" in bl:
            out["banlist_ocg"] = bl["ban_ocg"]
        if "ban_goat" in bl:
            out["banlist_goat"] = bl["ban_goat"]
    # 主要 set 名 (= card_sets の最新 = release date 新しい順、 ここでは最初要素)
    sets_list = card.get("card_sets") or []
    out["set_count"] = len(sets_list)
    if sets_list:
        # rarity / set_code は 主要 1 件のみ catalog specs に
        first = sets_list[0]
        out["primary_set_name"] = first.get("set_name", "")
        out["primary_set_code"] = first.get("set_code", "")
        out["primary_set_rarity"] = first.get("set_rarity", "")
    # 価格 (= ygoprodeck 取得時点)
    prices = card.get("card_prices") or []
    if prices:
        p = prices[0]
        for k in ("cardmarket_price", "tcgplayer_price", "ebay_price",
                  "amazon_price", "coolstuffinc_price"):
            v = p.get(k)
            if v and v not in ("0.00", "0"):
                out[f"price_{k.replace('_price', '')}_usd"] = v
    return out


def card_to_record(card: dict) -> Optional[dict]:
    """API card dict → catalog upsert 用 record."""
    cid = card.get("id")
    if not cid:
        return None
    name_ja = card.get("name") or ""
    name_en = card.get("name_en") or ""
    # language=ja 時: name=ja, name_en=en. 旧 langs 時 name のみ.
    if not name_en and name_ja:
        # ASCII alpha 含まないなら ja、 含むなら en と仮判定
        is_ascii_alpha = any(c.isascii() and c.isalpha() for c in name_ja)
        if is_ascii_alpha:
            name_en = name_ja
            name_ja = ""
    # 画像
    imgs = card.get("card_images") or []
    images = [img.get("image_url") for img in imgs if img.get("image_url")]
    return {
        "product_id": str(cid),
        "name": name_ja or name_en,
        "name_jp": name_ja or None,
        "name_en": name_en or name_ja,
        "set_name": (card.get("card_sets") or [{}])[0].get("set_name", ""),
        "specs": build_specs(card),
        "images": images[:3],  # 主要 3 枚まで
        "source_url": card.get("ygoprodeck_url", ""),
    }


def scrape(mode: str = "update", limit: Optional[int] = None,
           dry_run: bool = False) -> dict:
    """全 / 差分 投入.

    Returns:
        {added, updated, skipped, errors, total_processed}
    """
    started_at = time.strftime("%Y-%m-%dT%H:%M:%S")
    print(f"[{started_at}] Yu-Gi-Oh! TCG scrape: mode={mode} limit={limit} dry_run={dry_run}")

    cards = fetch_all_cards(language="ja")
    if limit:
        cards = cards[:limit]
        print(f"  limit applied: {len(cards)}")

    # 既存 product_id (mode='update' 用)
    existing_ids: set[str] = set()
    if mode == "update":
        import sqlite3
        conn = sqlite3.connect(str(api._DB_PATH))
        for (pid,) in conn.execute(
            "SELECT product_id FROM products WHERE category = ?", (CATEGORY,)
        ).fetchall():
            existing_ids.add(pid)
        conn.close()
        print(f"  existing catalog entries: {len(existing_ids)}")

    counts = {"added": 0, "updated": 0, "skipped": 0,
              "errors": 0, "total_processed": 0}
    for i, card in enumerate(cards, 1):
        rec = card_to_record(card)
        if not rec:
            counts["errors"] += 1
            continue
        pid = rec["product_id"]
        is_new = pid not in existing_ids
        if mode == "update" and not is_new:
            counts["skipped"] += 1
            continue
        if dry_run:
            counts["total_processed"] += 1
            if i <= 3:
                print(f"  [dry-run] {pid}: name_jp={rec['name_jp']!r} "
                      f"name_en={rec['name_en']!r}")
            continue
        try:
            api.upsert(
                category=CATEGORY,
                product_id=pid,
                name=rec["name"],
                name_jp=rec["name_jp"],
                name_en=rec["name_en"],
                name_en_source="ygoprodeck_official",
                set_name=rec["set_name"],
                specs=rec["specs"],
                images=rec["images"],
                source=SOURCE,
                source_url=rec["source_url"],
            )
            if is_new:
                counts["added"] += 1
            else:
                counts["updated"] += 1
            counts["total_processed"] += 1
        except Exception as e:
            counts["errors"] += 1
            if counts["errors"] <= 5:
                print(f"  ERR {pid}: {type(e).__name__}: {e}")

        if i % 1000 == 0:
            print(f"  progress: {i}/{len(cards)} (added={counts['added']}, "
                  f"skipped={counts['skipped']}, errors={counts['errors']})")

    print(f"\n=== 完了 ===")
    for k, v in counts.items():
        print(f"  {k}: {v}")
    return counts


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    p = argparse.ArgumentParser(description="Yu-Gi-Oh! TCG → iMakCatalog scraper")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--full", action="store_true", help="全件 scrape (既存上書き)")
    g.add_argument("--update", action="store_true", help="差分のみ (新規 product_id だけ)")
    p.add_argument("--limit", type=int, help="先頭 N 件のみ処理 (動作確認用)")
    p.add_argument("--dry-run", action="store_true",
                   help="DB に書かず record を確認")
    args = p.parse_args()

    if args.full:
        scrape(mode="full", limit=args.limit, dry_run=args.dry_run)
    elif args.update:
        scrape(mode="update", limit=args.limit, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
