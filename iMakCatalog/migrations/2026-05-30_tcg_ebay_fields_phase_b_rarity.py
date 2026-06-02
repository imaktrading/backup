"""TCG catalog Phase B: rarity_ebay 投入 (= 略語 → ロング表記 mapping).

依頼: 2026-05-30_tcg_set_name_english_field_mandate.md
+ 5/30 cycle Row 6 で「AR」 (= 略語) → eBay フィルタ「Art Rare」 (= ロング) 不一致発覚

mapping (= eBay フィルタ正規値準拠、 各カテゴリ別):

OPCG / Gundam / DBFW (= Bandai 系統一):
  C    → Common
  UC   → Uncommon
  R    → Rare
  SR   → Super Rare
  L    → Leader
  SP   → Special
  SR-A → Super Rare Alt Art (= 推定)
  P    → Promo
  DON  → DON!! Card

Pokemon (= AR/SAR/SR/UR 系):
  AR   → Art Rare
  SAR  → Special Art Rare
  SR   → Super Rare
  UR   → Ultra Rare
  SSR  → Secret Super Rare
  S    → Shiny (推定)
  HR   → Hyper Rare
  CHR  → Character Rare
  CSR  → Character Super Rare
  CHK  → Champion's Key (推定)
  PR   → Promo

YGO (= 既に英語 rarity だが正規化):
  Common         → Common
  Rare           → Rare
  Super Rare     → Super Rare
  Ultra Rare     → Ultra Rare
  Secret Rare    → Secret Rare
  Ultimate Rare  → Ultimate Rare
  Quarter Century Secret Rare → Quarter Century Secret Rare
  Collector's Rare → Collector's Rare
  Prismatic Secret Rare → Prismatic Secret Rare
  Starlight Rare → Starlight Rare
  Gold Rare      → Gold Rare
  (= 既に正規値なのでそのまま投入)
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

# Bandai 系 (OPCG / Gundam / DBFW) 共通 rarity 略語 → ロング表記
BANDAI_RARITY = {
    "C": "Common",
    "UC": "Uncommon",
    "R": "Rare",
    "SR": "Super Rare",
    "L": "Leader",
    "SP": "Special",
    "SR-A": "Super Rare Alt Art",
    "P": "Promo",
    "DON": "DON!! Card",
    "TR": "Treasure Rare",
    "PR": "Promo",
    "SEC": "Secret Rare",
    "LR": "Leader Rare",
    "PA": "Parallel",  # 推定
    "PARA": "Parallel",
}

POKEMON_RARITY = {
    "AR": "Art Rare",
    "SAR": "Special Art Rare",
    "SR": "Super Rare",
    "UR": "Ultra Rare",
    "SSR": "Secret Super Rare",
    "HR": "Hyper Rare",
    "CHR": "Character Rare",
    "CSR": "Character Super Rare",
    "S": "Shiny Rare",
    "PR": "Promo",
    "C": "Common",
    "U": "Uncommon",
    "R": "Rare",
    "RR": "Double Rare",  # eBay 正規値推定
    "RRR": "Triple Rare",
    "K": "Kira Rare",
    "TR": "Trainer Rare",
    "ACE": "ACE SPEC",
    "MA": "Master Ball",  # 推定
}

# YGO は既に英語、 正規化のみ (= ygoprodeck の生 rarity をそのまま投入)
# 例外: "Collector's Rare" のアポストロフィ正規化等

CATEGORY_MAPPING = {
    "pokemon_tcg": POKEMON_RARITY,
    "one_piece_tcg": BANDAI_RARITY,
    "gundam_tcg": BANDAI_RARITY,
    "dragonball_scg": BANDAI_RARITY,
    "yugioh_tcg": None,  # 既に英語、 そのまま採用
}


def resolve_rarity_ebay(category: str, rarity_raw: str) -> str | None:
    if not rarity_raw:
        return None
    rarity_raw = rarity_raw.strip()
    mapping = CATEGORY_MAPPING.get(category)
    if mapping is None:  # YGO
        return rarity_raw  # 既に英語、 そのまま採用
    # 略語 → ロング
    if rarity_raw in mapping:
        return mapping[rarity_raw]
    # 既に長い英語の可能性 (= 公式 import で投入された "Common" 等)
    if rarity_raw in mapping.values():
        return rarity_raw
    # 不明: そのまま返す (= 後で manual review)
    return rarity_raw


def process(dry_run: bool):
    print(f"=== Phase B rarity_ebay ({'DRY-RUN' if dry_run else 'APPLY'}) ===")
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    grand_updated = 0
    for cat in ["pokemon_tcg", "one_piece_tcg", "gundam_tcg", "dragonball_scg", "yugioh_tcg"]:
        rs = db.execute("SELECT id, specs FROM products WHERE category=?", (cat,)).fetchall()
        n = len(rs)
        c = 0
        for r in rs:
            try:
                specs = json.loads(r["specs"]) if r["specs"] else {}
            except Exception:
                specs = {}
            rarity_raw = specs.get("rarity", "")
            r_ebay = resolve_rarity_ebay(cat, rarity_raw)
            if r_ebay is None:
                continue
            if specs.get("rarity_ebay") == r_ebay:
                continue
            specs["rarity_ebay"] = r_ebay
            c += 1
            if not dry_run:
                db.execute(
                    "UPDATE products SET specs=?, updated_at=? WHERE id=?",
                    (json.dumps(specs, ensure_ascii=False), NOW, r["id"]),
                )
        if not dry_run:
            db.commit()
        grand_updated += c
        print(f"  {cat:<22} {n:>6,} | rarity_ebay+ {c:>5,}")
    db.close()
    print(f"\n=== grand updated: {grand_updated:,} ===")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--probe", action="store_true")
    args = p.parse_args()
    process(dry_run=args.probe)


if __name__ == "__main__":
    main()
