"""[DEPRECATED 2026-06-07 — 再実行禁止] PREFIX_TO_SET_EN は誤りを含む。

  SV1V↔SV1S 取り違え等の誤マッピングあり。HQ裁定で set_name_ebay の SSOT は
  ebay_filter_map/pokemon.yaml に一本化 (requests/2026-06-07_pokemon_mega_set_name_ebay_fix.md)。
  以後 set_name_ebay 修正は yaml 編集 + 再導出で行う。歴史的記録として残置 (削除しない)。

Pokemon set_name_ebay 投入 Step 1: 主要 set hardcode mapping.

依頼: 2026-05-30_phase_g2_pokemon_local_fetch_b_auto_expansion.md

Step 1 = 主要 set の手動 mapping (= 公式 EN 確認済 100+ set):
  - 拡張パック → "Booster Pack" 系統
  - ハイクラスパック → "High Class Pack"
  - スターターセット / プロモ等
  - 公式 EN 名 と JP 名を product_id prefix で連動

Step 2 (= 別 task) = 残 set の自動 fetch (= pokemon-card.com EN / pokellector)

実行:
  python iMakCatalog/migrations/2026-05-30_pokemon_set_name_ebay_hardcode.py --probe
  python iMakCatalog/migrations/2026-05-30_pokemon_set_name_ebay_hardcode.py
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
NOW = datetime.now().isoformat()

# product_id prefix → eBay set 名 (= 公式 EN 準拠)
# SV (Scarlet & Violet) 系 / SM 系 / XY 系 / BW 系 等
PREFIX_TO_SET_EN = {
    # === SV 系 (Scarlet & Violet) ===
    "SV1V": "Scarlet ex",
    "SV1S": "Violet ex",
    "SV2P": "Triplet Beat",
    "SV2D": "Snow Hazard",
    "SV2a": "Pokemon Card 151",
    "SV3": "Ruler of the Black Flame",
    "SV3a": "Raging Surf",
    "SV4K": "Ancient Roar",
    "SV4M": "Future Flash",
    "SV4a": "Shiny Treasure ex",
    "SV5K": "Wild Force",
    "SV5M": "Cyber Judge",
    "SV5a": "Crimson Haze",
    "SV6": "Mask of Change",
    "SV6a": "Night Wanderer",
    "SV7": "Stellar Miracle",
    "SV7a": "Paradise Dragona",
    "SV8": "Super Electric Breaker",
    "SV8a": "Terastal Festival ex",
    "SV9": "Battle Partners",
    "SV9a": "Heat Wave Arena",
    "SV10": "Rocket Gang's Glory",
    "SV11W": "Black Bolt",
    "SV11B": "White Flare",
    "SV12": "Mega Brave",
    "M2a": "Mega Symphonia",
    "M3": "Mega Dimension",
    # === SM 系 (Sun & Moon) ===
    "SM1S": "Collection Sun",
    "SM1M": "Collection Moon",
    "SM2K": "Alolan Moonlight",
    "SM2L": "Alolan Starlight",
    "SM3N": "To Have Seen the Battle Rainbow",
    "SM3H": "Awakened Heroes",
    "SM3+": "Shining Legends",
    "SM4A": "Ultra Sun",
    "SM4B": "Ultra Moon",
    "SM5S": "Ultra Force",
    "SM5M": "Ultra Shiny",
    "SM6": "Forbidden Light",
    "SM6a": "Dragon Storm",
    "SM7": "Thunderclap Spark",
    "SM7a": "Sky-Splitting Charisma",
    "SM7b": "Fairy Rise",
    "SM8": "Super Burst Impact",
    "SM8a": "Dark Order",
    "SM8b": "GX Ultra Shiny",
    "SM9": "Tag Bolt",
    "SM9a": "Night Unison",
    "SM9b": "Full Metal Wall",
    "SM10": "Double Blaze",
    "SM10a": "Sky Legend",
    "SM10b": "Sky Forming Tower",
    "SM11a": "Remix Bout",
    "SM11b": "Dream League",
    "SM12": "Alter Genesis",
    "SM12a": "TAG TEAM GX Tag All Stars",
    # === S 系 (Sword & Shield) ===
    "S1W": "Sword",
    "S1H": "Shield",
    "S1a": "VMAX Rising",
    "S2": "Rebellion Crash",
    "S2a": "Explosive Walker",
    "S3": "Infinity Zone",
    "S3a": "Legendary Heartbeat",
    "S4": "Shocking Volt Tackle",
    "S4a": "Shiny Star V",
    "S5I": "Single Strike Master",
    "S5R": "Rapid Strike Master",
    "S5a": "Matchless Fighters",
    "S6H": "Silver Lance",
    "S6K": "Jet-Black Poltergeist",
    "S6a": "Eevee Heroes",
    "S7D": "Skyscraping Perfect",
    "S7R": "Blue Sky Stream",
    "S7a": "Sky Stream Energy",
    "S8": "Fusion Arts",
    "S8a": "25th Anniversary Collection",
    "S8b": "VMAX Climax",
    "S9": "Star Birth",
    "S9a": "Battle Region",
    "S10D": "Time Gazer",
    "S10P": "Space Juggler",
    "S10a": "Dark Phantasma",
    "S11": "Lost Abyss",
    "S11a": "Incandescent Arcana",
    "S12": "Paradigm Trigger",
    "S12a": "VSTAR Universe",
    # === XY 系 ===
    "XY1": "Collection X",
    "XY2": "Collection Y",
    "XY3": "Rising Fist",
    "XY4": "Phantom Gate",
    "XY5": "Tidal Storm",
    "XY6": "Emerald Break",
    "XY7": "Bandit Ring",
    "XY8": "Red Flash",
    "XY9": "Blue Shock",
    "XY10": "Awakening Psychic King",
    "XY11": "Explosive Fighter Xerneas",
    "XYP": "XY Promo",
    "XY-BREAK": "BREAKthrough",
    # === BW 系 ===
    "BW1": "Black Collection",
    "BW2": "White Collection",
    "BWP": "BW Promo",
    # === Movie Card 等 ===
    "MC": "Movie Commemoration",
    # === Promo 系 ===
    "SI": "Special Item",
    "SVM": "Scarlet & Violet Promo",
    "SVMP": "Scarlet & Violet Promo",
    "SM-P": "Sun & Moon Promo",
    "S-P": "Sword & Shield Promo",
    "P": "Promo",
}


def process(dry_run: bool):
    print(f"=== Pokemon set_name_ebay hardcode ({'DRY-RUN' if dry_run else 'APPLY'}) ===")
    print(f"  mappings defined: {len(PREFIX_TO_SET_EN)}")
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    rs = db.execute(
        "SELECT id, product_id, specs FROM products WHERE category='pokemon_tcg'"
    ).fetchall()
    n = len(rs)
    updated = 0
    no_match = 0
    for r in rs:
        try:
            specs = json.loads(r["specs"]) if r["specs"] else {}
        except Exception:
            specs = {}
        if "set_name_ebay" in specs:
            continue
        # product_id から prefix 抽出
        m = re.match(r"^([A-Za-z0-9-]+?)-?\d", r["product_id"])
        if not m:
            no_match += 1
            continue
        pfx = m.group(1).rstrip("-")
        # 完全一致 → 部分一致順
        set_en = PREFIX_TO_SET_EN.get(pfx)
        if not set_en:
            # 一文字短くして再 try (= SV4aP → SV4a 等)
            for cand in (pfx[:-1], pfx[:-2]):
                if cand and cand in PREFIX_TO_SET_EN:
                    set_en = PREFIX_TO_SET_EN[cand]
                    break
        if not set_en:
            no_match += 1
            continue
        specs["set_name_ebay"] = set_en
        updated += 1
        if not dry_run:
            db.execute(
                "UPDATE products SET specs=?, updated_at=? WHERE id=?",
                (json.dumps(specs, ensure_ascii=False), NOW, r["id"]),
            )
    if not dry_run:
        db.commit()
    db.close()
    print(f"\n  total: {n:,}")
    print(f"  updated: {updated:,} ({updated/n*100:.1f}%)")
    print(f"  no_match: {no_match:,}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--probe", action="store_true")
    args = p.parse_args()
    process(dry_run=args.probe)


if __name__ == "__main__":
    main()
