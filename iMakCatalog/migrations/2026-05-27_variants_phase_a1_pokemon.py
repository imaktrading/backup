"""variant Phase A.1: Pokemon 21,855 件 variants JSON 投入.

依頼: 2026-05-27_catalog_variant_meta_phase_a_implementation.md
Step 2 本実装 (= POC 完了後).

設計:
  - specs.rarity → variant_code 派生 (= 14 rarity codes 対象)
  - variants JSON = {"<variant_code>": {features, finish, rarity_ebay, title_token}}
  - 1 product_id = 1 variant (= 同 product_id で複数 variants が必要なら multi-variant 拡張可能形)
  - rarity 不在 (= 9,567 件) / C / U / その他 → variants=NULL (= skip)

実行:
    python migrations/2026-05-27_variants_phase_a1_pokemon.py --probe    # 件数集計のみ
    python migrations/2026-05-27_variants_phase_a1_pokemon.py --dry-run  # 投入 plan 出すが DB 触らず
    python migrations/2026-05-27_variants_phase_a1_pokemon.py            # 本走
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import api  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

DB = str(api._DB_PATH)
NOW = datetime.now().isoformat()


# ============================================================================
# Pokemon variant_code → eBay 公式値 mapping
# ============================================================================
# eBay 公式フィルタ値: Pokemon TCG Individual Cards カテゴリで観察される表記
# (= 一般的な TOP seller 採用表記、 実 eBay フィルタ UI で 5-10 件 sample verify 推奨)
_POKEMON_RARITY_TO_VARIANT_META = {
    # Art Rare 系 (= illustrative art focus)
    "AR":  {"features": "Art Rare",            "finish": "Holo", "rarity_ebay": "Art Rare",            "title_token": "Art Rare"},
    "SAR": {"features": "Special Art Rare",    "finish": "Holo", "rarity_ebay": "Special Art Rare",    "title_token": "Special Art Rare"},
    # Rare 階梯
    "R":   {"features": "Rare",                "finish": "",     "rarity_ebay": "Rare",                "title_token": ""},
    "RR":  {"features": "Double Rare",         "finish": "Holo", "rarity_ebay": "Double Rare",         "title_token": "Double Rare"},
    "RRR": {"features": "Triple Diamond Rare", "finish": "Holo", "rarity_ebay": "Triple Diamond Rare", "title_token": "Triple Diamond Rare"},
    "SR":  {"features": "Super Rare",          "finish": "Holo", "rarity_ebay": "Super Rare",          "title_token": "Super Rare"},
    "UR":  {"features": "Ultra Rare",          "finish": "Holo", "rarity_ebay": "Ultra Rare",          "title_token": "Ultra Rare"},
    "HR":  {"features": "Hyper Rare",          "finish": "Holo", "rarity_ebay": "Hyper Rare",          "title_token": "Hyper Rare"},
    # Specialty
    "MA":  {"features": "Master",              "finish": "Holo", "rarity_ebay": "Master",              "title_token": "Master"},
    "SSR": {"features": "Shiny Super Rare",    "finish": "Holo", "rarity_ebay": "Shiny Super Rare",    "title_token": "Shiny Super Rare"},
    "CHR": {"features": "Character Rare",      "finish": "Holo", "rarity_ebay": "Character Rare",      "title_token": "Character Rare"},
    "CSR": {"features": "Character Super Rare","finish": "Holo", "rarity_ebay": "Character Super Rare","title_token": "Character Super Rare"},
    "TR":  {"features": "Trainer Rare",        "finish": "Holo", "rarity_ebay": "Trainer Rare",        "title_token": "Trainer Rare"},
    "S":   {"features": "Shiny",               "finish": "Holo", "rarity_ebay": "Shiny",               "title_token": "Shiny"},
    "SS":  {"features": "Shiny Star",          "finish": "Holo", "rarity_ebay": "Shiny Star",          "title_token": "Shiny Star"},
}


def derive_variants_json(rarity: str) -> str | None:
    """specs.rarity から variants JSON 生成. 該当なし → None."""
    if not rarity or rarity not in _POKEMON_RARITY_TO_VARIANT_META:
        return None
    variants = {rarity: _POKEMON_RARITY_TO_VARIANT_META[rarity]}
    return json.dumps(variants, ensure_ascii=False)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--probe", action="store_true", help="件数集計のみ")
    p.add_argument("--dry-run", action="store_true", help="DB 触らず投入 plan 表示")
    p.add_argument("--limit", type=int, help="先頭 N 件のみ処理")
    args = p.parse_args()

    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row

    rows = db.execute(
        "SELECT id, product_id, specs FROM products WHERE category='pokemon_tcg' ORDER BY id"
    ).fetchall()
    print(f"Pokemon total: {len(rows)}")

    rarity_cnt = Counter()
    target_rows = []
    skip_no_rarity = 0
    skip_no_mapping = 0
    for r in rows:
        try:
            specs = json.loads(r["specs"])
        except Exception:
            specs = {}
        rarity = specs.get("rarity")
        if not rarity:
            skip_no_rarity += 1
            continue
        rarity_cnt[rarity] += 1
        if rarity not in _POKEMON_RARITY_TO_VARIANT_META:
            skip_no_mapping += 1
            continue
        target_rows.append((r["id"], r["product_id"], rarity))

    print()
    print("=== rarity 分布 (= variant_code 投入可否) ===")
    for r, n in rarity_cnt.most_common():
        flag = "✓" if r in _POKEMON_RARITY_TO_VARIANT_META else "skip"
        print(f"  [{flag}] {r:8s}: {n}")
    print()
    print(f"  対象 target: {len(target_rows)}")
    print(f"  skip (rarity 不在): {skip_no_rarity}")
    print(f"  skip (mapping 不在): {skip_no_mapping}")

    if args.probe:
        db.close()
        return

    if args.limit:
        target_rows = target_rows[: args.limit]
        print(f"\nLIMIT: 先頭 {len(target_rows)} 件")

    # 投入
    updated = 0
    for tid, pid, rarity in target_rows:
        variants_json = derive_variants_json(rarity)
        if not variants_json:
            continue
        if args.dry_run:
            updated += 1
            continue
        db.execute(
            "UPDATE products SET variants=?, updated_at=? WHERE id=?",
            (variants_json, NOW, tid),
        )
        updated += 1
        if updated % 500 == 0:
            db.commit()
            print(f"    ... {updated}/{len(target_rows)} done")
    if not args.dry_run:
        db.commit()

    db.close()
    print()
    print(f"=== 完了 ===")
    print(f"  UPDATE: {updated} {'(dry-run)' if args.dry_run else ''}")


if __name__ == "__main__":
    main()
