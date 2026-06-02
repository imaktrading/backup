"""遊戯王 ygoprodeck full dump → 全 rarity 完全展開 (PREMIUM 拡張版).

依頼: ユーザー指示 (2026-05-30) 26% → 完全網羅 (= 全 rarity + base 不在 passcode)

flow:
  1. ygoprodeck dump 読込
  2. **全 rarity** (= Common / Rare / Short Print / Premium 全部) で 1 passcode × 1 set_code = 1 entry
  3. card_sets 不在の passcode は base entry (= product_id = passcode のみ) で INSERT
  4. 既存 product_id 重複は skip

product_id 命名:
  - set あり: `{passcode}_{set_code}` (= 例 89631139_LON-EN040)
  - set なし: `{passcode}` (= base only)

実行:
  python iMakCatalog/migrations/2026-05-30_ygo_full_expansion.py --probe
  python iMakCatalog/migrations/2026-05-30_ygo_full_expansion.py
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


def _rarity_to_variant_type(rarity: str) -> str:
    """全 rarity → variant_type tag (= 正規化)."""
    if not rarity:
        return "base"
    s = rarity.lower().replace("'", "").replace(" ", "_")
    return s


def _safe_pid(passcode: int, set_code: str = "") -> str:
    if set_code:
        sc = re.sub(r"[^\w\-]", "_", set_code)
        return f"{passcode}_{sc}"
    return str(passcode)


def _build_specs(card: dict, set_entry: dict | None) -> dict:
    specs = {
        "card_type": card.get("type", ""),
        "race": card.get("race", ""),
        "attribute": card.get("attribute", ""),
    }
    for k_src, k_dst in [("atk", "atk"), ("def", "def"), ("level", "level"),
                          ("linkval", "link_val"), ("scale", "pendulum_scale")]:
        v = card.get(k_src)
        if v is not None:
            specs[k_dst] = v
    if card.get("archetype"):
        specs["archetype"] = card["archetype"]
    if set_entry:
        specs["set_code"] = set_entry.get("set_code", "")
        specs["rarity"] = set_entry.get("set_rarity", "")
        specs["set_rarity_code"] = set_entry.get("set_rarity_code", "")
        specs["variant_type"] = _rarity_to_variant_type(set_entry.get("set_rarity", ""))
        try:
            p = float(set_entry.get("set_price") or 0)
            if p > 0:
                specs["tcgplayer_price_usd"] = p
        except Exception:
            pass
    else:
        specs["variant_type"] = "base"
    return specs


def process(dry_run: bool):
    print(f"=== YGO FULL expansion ({'DRY-RUN' if dry_run else 'APPLY'}) ===")
    if not DUMP_FILE.exists():
        print(f"  ⚠️ dump file not found")
        return
    cards = json.loads(DUMP_FILE.read_text(encoding="utf-8"))
    print(f"  ygoprodeck cards: {len(cards):,}")

    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    existing_ids = {
        r["product_id"]
        for r in db.execute(
            "SELECT product_id FROM products WHERE category='yugioh_tcg'"
        ).fetchall()
    }
    print(f"  catalog 既存 YGO product_ids: {len(existing_ids):,}")

    counts = {"INSERT_variant": 0, "INSERT_base": 0, "DUP_SKIP": 0}
    inserted_pids = set()
    for card in cards:
        passcode = card.get("id")
        if not passcode:
            continue
        sets = card.get("card_sets") or []
        image_url = ""
        imgs = card.get("card_images") or []
        if imgs:
            image_url = imgs[0].get("image_url", "")
        name = card.get("name", "")

        if sets:
            for set_entry in sets:
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
                    counts["INSERT_variant"] += 1
                    continue
                db.execute(
                    """INSERT INTO products
                       (category, product_id, name, name_en, name_en_source,
                        set_name_official, specs, images, source, source_url,
                        created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        "yugioh_tcg", pid, name, name, "ygoprodeck",
                        set_entry.get("set_name", ""),
                        json.dumps(specs, ensure_ascii=False),
                        json.dumps([image_url] if image_url else [], ensure_ascii=False),
                        "ygoprodeck_full_expansion",
                        f"https://db.ygoprodeck.com/card/?search={passcode}",
                        NOW, NOW,
                    ),
                )
                counts["INSERT_variant"] += 1
                if counts["INSERT_variant"] % 2000 == 0 and not dry_run:
                    db.commit()
                    print(f"  ... variant {counts['INSERT_variant']:,}")
        else:
            # base 不在 (= card_sets が無い、 例: 古い / 海外限定)
            pid = _safe_pid(passcode)
            if pid in existing_ids or pid in inserted_pids:
                counts["DUP_SKIP"] += 1
                continue
            inserted_pids.add(pid)
            specs = _build_specs(card, None)
            if dry_run:
                counts["INSERT_base"] += 1
                continue
            db.execute(
                """INSERT INTO products
                   (category, product_id, name, name_en, name_en_source,
                    specs, images, source, source_url, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    "yugioh_tcg", pid, name, name, "ygoprodeck",
                    json.dumps(specs, ensure_ascii=False),
                    json.dumps([image_url] if image_url else [], ensure_ascii=False),
                    "ygoprodeck_full_expansion",
                    f"https://db.ygoprodeck.com/card/?search={passcode}",
                    NOW, NOW,
                ),
            )
            counts["INSERT_base"] += 1

    if not dry_run:
        db.commit()
    db.close()
    print(f"\n=== result ===")
    print(f"  INSERT_variant: {counts['INSERT_variant']:,}")
    print(f"  INSERT_base:    {counts['INSERT_base']:,}")
    print(f"  DUP_SKIP:       {counts['DUP_SKIP']:,}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--probe", action="store_true")
    args = p.parse_args()
    process(dry_run=args.probe)


if __name__ == "__main__":
    main()
