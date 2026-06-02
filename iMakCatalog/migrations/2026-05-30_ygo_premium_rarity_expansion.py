"""遊戯王 ygoprodeck full dump → PREMIUM rarity print 1:N 展開 (catalog INSERT).

依頼: ユーザー指示 (2026-05-30) Phase 1 YGO variant 完整性
+ 案 B PREMIUM rarity 絞り込み (= 13,207 件規模、 ユーザー判断確定)

flow:
  1. _ygoprodeck_full_dump.json 読込 (= 14,371 cards、 既取得)
  2. PREMIUM rarity (= Secret/Ultra/Ultimate/Quarter Century/Prismatic/Collector/Starlight/Gold/Ghost 系) のみ抽出
  3. 1 passcode × 1 set_code = 1 variant entry
  4. catalog 既存 base passcode entry は維持、 variant は別 product_id で INSERT
  5. product_id 命名: `{passcode}_{set_code}` (= 例 89631139_LON-EN040)

field mapping (= ygoprodeck → catalog specs):
  type            → card_type
  atk / def       → atk / def
  level / linkval → level
  attribute       → attribute
  race            → race
  set_code        → set_code
  set_rarity      → rarity
  set_rarity_code → rarity_code
  set_price       → tcgplayer_price_usd
  set_name        → set_name_official

実行:
  python iMakCatalog/migrations/2026-05-30_ygo_premium_rarity_expansion.py --probe
  python iMakCatalog/migrations/2026-05-30_ygo_premium_rarity_expansion.py
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import api  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

DB_PATH = str(api._DB_PATH)
DUMP_FILE = Path("C:/dev/iMak_data/catalog/_ygoprodeck_full_dump.json")
NOW = datetime.now().isoformat()

PREMIUM_RARITIES = {
    "Secret Rare",
    "Ultra Rare",
    "Ultimate Rare",
    "Quarter Century Secret Rare",
    "Platinum Secret Rare",
    "Prismatic Secret Rare",
    "Collector's Rare",
    "Starlight Rare",
    "Gold Rare",
    "Premium Gold Rare",
    "Gold Secret Rare",
    "Ghost Rare",
    "Ghost Gold Rare",
    "Mosaic Rare",
    "Shatterfoil Rare",
    "Starfoil Rare",
}

RARITY_TO_VARIANT_TYPE = {
    "Secret Rare": "secret_rare",
    "Ultra Rare": "ultra_rare",
    "Ultimate Rare": "ultimate_rare",
    "Quarter Century Secret Rare": "quarter_century_secret",
    "Platinum Secret Rare": "platinum_secret",
    "Prismatic Secret Rare": "prismatic_secret",
    "Collector's Rare": "collectors_rare",
    "Starlight Rare": "starlight_rare",
    "Gold Rare": "gold_rare",
    "Premium Gold Rare": "premium_gold",
    "Gold Secret Rare": "gold_secret",
    "Ghost Rare": "ghost_rare",
    "Ghost Gold Rare": "ghost_gold",
    "Mosaic Rare": "mosaic_rare",
    "Shatterfoil Rare": "shatterfoil_rare",
    "Starfoil Rare": "starfoil_rare",
}


def _safe_pid(passcode: int, set_code: str) -> str:
    """product_id 命名: `{passcode}_{set_code}` (= 例 89631139_LON-EN040)."""
    sc = re.sub(r"[^\w\-]", "_", set_code)
    return f"{passcode}_{sc}"


def _build_specs(card: dict, set_entry: dict) -> dict:
    """ygoprodeck card + 1 set_entry → catalog specs dict."""
    specs = {
        "card_type": card.get("type", ""),
        "race": card.get("race", ""),
        "attribute": card.get("attribute", ""),
        "set_code": set_entry.get("set_code", ""),
        "set_rarity_code": set_entry.get("set_rarity_code", ""),
        "rarity": set_entry.get("set_rarity", ""),
        "variant_type": RARITY_TO_VARIANT_TYPE.get(
            set_entry.get("set_rarity", ""), "premium"
        ),
    }
    # 数値 field
    for k_src, k_dst in [("atk", "atk"), ("def", "def"), ("level", "level"),
                          ("linkval", "link_val"), ("scale", "pendulum_scale")]:
        v = card.get(k_src)
        if v is not None:
            specs[k_dst] = v
    # price
    try:
        p = float(set_entry.get("set_price") or 0)
        if p > 0:
            specs["tcgplayer_price_usd"] = p
    except Exception:
        pass
    # archetype
    if card.get("archetype"):
        specs["archetype"] = card["archetype"]
    return specs


def process(dry_run: bool):
    print(f"=== YGO PREMIUM rarity expansion ({'DRY-RUN' if dry_run else 'APPLY'}) ===")
    if not DUMP_FILE.exists():
        print(f"  ⚠️ dump file not found: {DUMP_FILE}")
        return
    cards = json.loads(DUMP_FILE.read_text(encoding="utf-8"))
    print(f"  ygoprodeck cards: {len(cards):,}")

    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    # 既存 YGO product_id set (= 重複 INSERT 防止)
    existing_ids = {
        r["product_id"]
        for r in db.execute(
            "SELECT product_id FROM products WHERE category='yugioh_tcg'"
        ).fetchall()
    }
    print(f"  catalog 既存 YGO product_ids: {len(existing_ids):,}")

    counts = {"INSERT": 0, "DUP_SKIP": 0, "NOT_PREMIUM": 0, "NO_SET": 0}
    inserted_pids = set()
    for card in cards:
        passcode = card.get("id")
        if not passcode:
            counts["NO_SET"] += 1
            continue
        sets = card.get("card_sets") or []
        if not sets:
            counts["NO_SET"] += 1
            continue
        image_url = ""
        imgs = card.get("card_images") or []
        if imgs:
            image_url = imgs[0].get("image_url", "")
        name = card.get("name", "")
        archetype = card.get("archetype", "")

        for set_entry in sets:
            rarity = set_entry.get("set_rarity", "")
            if rarity not in PREMIUM_RARITIES:
                counts["NOT_PREMIUM"] += 1
                continue
            set_code = set_entry.get("set_code", "")
            if not set_code:
                continue
            pid = _safe_pid(passcode, set_code)
            if pid in existing_ids or pid in inserted_pids:
                counts["DUP_SKIP"] += 1
                continue
            inserted_pids.add(pid)
            specs = _build_specs(card, set_entry)
            if dry_run:
                counts["INSERT"] += 1
                continue
            db.execute(
                """INSERT INTO products
                   (category, product_id, name, name_en, name_en_source,
                    set_name_official, specs, images, source, source_url,
                    created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    "yugioh_tcg",
                    pid,
                    name,
                    name,
                    "ygoprodeck",
                    set_entry.get("set_name", ""),
                    json.dumps(specs, ensure_ascii=False),
                    json.dumps([image_url] if image_url else [], ensure_ascii=False),
                    "ygoprodeck_premium_expansion",
                    f"https://db.ygoprodeck.com/card/?search={passcode}",
                    NOW, NOW,
                ),
            )
            counts["INSERT"] += 1
            if counts["INSERT"] % 500 == 0 and not dry_run:
                db.commit()
                print(f"  ... {counts['INSERT']:,} INSERT")

    if not dry_run:
        db.commit()
    db.close()
    print(f"\n=== result ===")
    print(f"  INSERT:     {counts['INSERT']:,}")
    print(f"  DUP_SKIP:   {counts['DUP_SKIP']:,}")
    print(f"  NOT_PREMIUM:{counts['NOT_PREMIUM']:,}")
    print(f"  NO_SET:     {counts['NO_SET']:,}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--probe", action="store_true")
    args = p.parse_args()
    process(dry_run=args.probe)


if __name__ == "__main__":
    main()
