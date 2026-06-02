"""TCG catalog Phase C/D/E/F: Character / card_type_ebay / Features / Finish 投入.

依頼: 2026-05-30_tcg_set_name_english_field_mandate.md

Phase F (Finish):
  - "Non-Foil" / "Foil" / "Holo" 等
  - 判定 logic:
    - rarity_ebay = Common / Uncommon → "Non-Foil"
    - rarity_ebay = Rare / Super Rare / Ultra Rare / Secret Rare 系 → "Foil"
    - rarity_ebay = Art Rare / Special Art Rare / Hyper Rare → "Holo"
    - variant_type = alt_art / parallel / leader / premium_booster → "Foil"
    - variant_type = promo → "Foil"

Phase E (Features):
  - list 形式 ["Alt Art" / "Full Art" / 等]
  - variant_type 由来:
    - alt_art → ["Alt Art"]
    - premium_booster → ["Full Art"]
    - leader → ["Leader Card"]
  - rarity 由来:
    - Art Rare / Special Art Rare → ["Art Card"]
    - Secret Rare / Hyper Rare → ["Secret"]

Phase D (card_type_ebay):
  - category 別 eBay フィルタ正規値
  - Pokemon: "Character" → "Pokémon Card"、 "Trainer" → "Trainer Card" 等
  - OPCG/Gundam/DBFW: 既存 card_type を 英語化
  - YGO: Monster Card / Spell Card / Trap Card 正規化

Phase C (character_name):
  - Pokemon: name = character (= "Pikachu" 等)
  - OPCG/Gundam/DBFW: name = character の多くケース (= "Monkey D. Luffy")
  - 簡易対応: name_jp or name 採用 (= 既存 name で投入、 後で精緻化)

実行:
  python iMakCatalog/migrations/2026-05-30_tcg_ebay_fields_phase_cdef.py
"""
from __future__ import annotations

import argparse
import json
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

# Phase F: Finish 判定
HOLO_RARITIES = {"Art Rare", "Special Art Rare", "Hyper Rare", "Character Super Rare",
                  "Quarter Century Secret Rare", "Prismatic Secret Rare",
                  "Starlight Rare", "Collector's Rare", "Ghost Rare"}
FOIL_RARITIES = {"Rare", "Super Rare", "Ultra Rare", "Secret Rare", "Ultimate Rare",
                  "Double Rare", "Triple Rare", "Promo", "Leader", "Special",
                  "Treasure Rare", "Secret Super Rare", "Ghost Rare", "Gold Rare",
                  "Premium Gold Rare", "Gold Secret Rare", "Platinum Secret Rare"}
NON_FOIL_RARITIES = {"Common", "Uncommon", "Shiny Rare"}

FOIL_VARIANT_TYPES = {"alt_art", "parallel", "leader", "premium_booster",
                      "promo", "starter_deck", "limited_product", "event"}

# Phase E: Features 派生
def derive_features(specs: dict) -> list[str]:
    feats: list[str] = []
    vt = specs.get("variant_type", "")
    if vt == "alt_art":
        feats.append("Alt Art")
    elif vt == "premium_booster":
        feats.append("Full Art")
    elif vt == "leader":
        feats.append("Leader Card")
    elif vt == "limited_product":
        feats.append("Limited Edition")
    elif vt == "promo":
        feats.append("Promo")
    rarity = (specs.get("rarity_ebay") or "").strip()
    if rarity in ("Art Rare", "Special Art Rare", "Character Rare", "Character Super Rare"):
        feats.append("Art Card")
    if rarity in ("Secret Rare", "Hyper Rare", "Quarter Century Secret Rare",
                  "Prismatic Secret Rare", "Starlight Rare"):
        feats.append("Secret")
    if rarity == "Ultra Rare":
        feats.append("Ultra Rare")
    # dedup + order keep
    seen = set()
    out = []
    for f in feats:
        if f not in seen:
            seen.add(f)
            out.append(f)
    return out


# Phase F: Finish 派生
def derive_finish(specs: dict) -> str:
    rarity = (specs.get("rarity_ebay") or "").strip()
    vt = specs.get("variant_type", "")
    if rarity in HOLO_RARITIES:
        return "Holo"
    if vt in FOIL_VARIANT_TYPES:
        return "Foil"
    if rarity in FOIL_RARITIES:
        return "Foil"
    if rarity in NON_FOIL_RARITIES:
        return "Non-Foil"
    return "Non-Foil"  # default fallback


# Phase D: card_type_ebay mapping
CARD_TYPE_EBAY_MAPPING = {
    # Pokemon (= 既存 specs.card_type は "Character" / "Trainer" / "Energy" 等想定)
    "pokemon_tcg": {
        "Character": "Pokémon Card",
        "Trainer": "Trainer Card",
        "Energy": "Energy Card",
        "Pokémon": "Pokémon Card",
        "Item": "Item Card",
        "Supporter": "Supporter Card",
        "Stadium": "Stadium Card",
        "Tool": "Tool Card",
    },
    # OPCG (= 既存 specs.card_type は "CHARACTER" / "LEADER" / "EVENT" / "STAGE")
    "one_piece_tcg": {
        "CHARACTER": "Character Card",
        "LEADER": "Leader Card",
        "EVENT": "Event Card",
        "STAGE": "Stage Card",
        "DON!!": "DON!! Card",
    },
    # Gundam (= UNIT / PILOT / COMMAND / BASE / RESOURCE / EX BASE)
    "gundam_tcg": {
        "UNIT": "Unit Card",
        "PILOT": "Pilot Card",
        "COMMAND": "Command Card",
        "BASE": "Base Card",
        "RESOURCE": "Resource Card",
        "EX BASE": "EX Base Card",
        "EX RESOURCE": "EX Resource Card",
        "UNIT TOKEN": "Unit Token Card",
    },
    # DBFW
    "dragonball_scg": {
        "LEADER": "Leader Card",
        "BATTLE": "Battle Card",
        "EXTRA": "Extra Card",
        "UNISON": "Unison Card",
    },
    # YGO (= ygoprodeck の type 値)
    "yugioh_tcg": {
        # 既存 type 値そのまま英語、 正規化
    },
}


def resolve_card_type_ebay(category: str, raw: str) -> str | None:
    if not raw:
        return None
    mp = CARD_TYPE_EBAY_MAPPING.get(category, {})
    if raw in mp:
        return mp[raw]
    # YGO は ygoprodeck の英 type そのまま採用
    if category == "yugioh_tcg":
        return raw
    return None


# Phase C: character_name 派生 (= 簡易 = name 採用)
def derive_character_name(name: str, name_jp: str) -> str | None:
    # 既存 name (= 英) があればそれ、 なければ name_jp
    return name or name_jp or None


def process(dry_run: bool):
    print(f"=== Phase C/D/E/F ({'DRY-RUN' if dry_run else 'APPLY'}) ===")
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    grand = {"updated": 0, "finish": 0, "features": 0, "card_type_ebay": 0, "char": 0}
    for cat in ["pokemon_tcg", "one_piece_tcg", "gundam_tcg", "dragonball_scg", "yugioh_tcg"]:
        rs = db.execute(
            "SELECT id, name, name_jp, specs FROM products WHERE category=?", (cat,)
        ).fetchall()
        n = len(rs)
        c = {"updated": 0, "finish": 0, "features": 0, "card_type_ebay": 0, "char": 0}
        for r in rs:
            try:
                specs = json.loads(r["specs"]) if r["specs"] else {}
            except Exception:
                specs = {}
            changed = False
            # Phase F
            if "finish" not in specs:
                finish = derive_finish(specs)
                if finish:
                    specs["finish"] = finish
                    c["finish"] += 1
                    changed = True
            # Phase E
            if "features" not in specs:
                feats = derive_features(specs)
                if feats:
                    specs["features"] = feats
                    c["features"] += 1
                    changed = True
            # Phase D
            if "card_type_ebay" not in specs:
                cte = resolve_card_type_ebay(cat, specs.get("card_type", "") or specs.get("type_en", ""))
                if cte:
                    specs["card_type_ebay"] = cte
                    c["card_type_ebay"] += 1
                    changed = True
            # Phase C
            if "character_name" not in specs:
                cn = derive_character_name(r["name"], r["name_jp"])
                if cn:
                    specs["character_name"] = cn
                    c["char"] += 1
                    changed = True
            if changed:
                c["updated"] += 1
                if not dry_run:
                    db.execute(
                        "UPDATE products SET specs=?, updated_at=? WHERE id=?",
                        (json.dumps(specs, ensure_ascii=False), NOW, r["id"]),
                    )
        if not dry_run:
            db.commit()
        for k in c:
            if k in grand:
                grand[k] += c[k]
            else:
                grand[k] = c[k]
        print(f"  {cat:<22} {n:>6,} | updated={c['updated']:>5,} "
              f"finish+={c['finish']:>5,} feat+={c['features']:>4,} "
              f"type+={c['card_type_ebay']:>5,} char+={c['char']:>5,}")
    db.close()
    print(f"\n=== grand ===")
    for k in ("updated", "finish", "features", "card_type_ebay", "char"):
        print(f"  {k:<18} {grand[k]:,}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--probe", action="store_true")
    args = p.parse_args()
    process(dry_run=args.probe)


if __name__ == "__main__":
    main()
