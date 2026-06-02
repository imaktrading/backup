"""TCG catalog Phase A: 即時投入可な 4 field 一括追加.

依頼: 2026-05-30_tcg_set_name_english_field_mandate.md (= 改訂版 simple)

対象 field (Phase A = 即時可、 EN scrape 不要):
  - card_size_ebay: 全 TCG "Standard" default
  - game_ebay: category 別 eBay フィルタ正規値 (= 仮置き、 後で調整可)
  - language: category + product_id pattern から推定
  - release_year: set_name / product_id / specs.year から抽出

設計原則 (= 依頼書 2.1):
  - 既存 field 触らない
  - specs JSON 内に純追加
  - 全 TCG 5 cat 一括投入

実行:
  python iMakCatalog/migrations/2026-05-30_tcg_ebay_fields_phase_a.py --probe
  python iMakCatalog/migrations/2026-05-30_tcg_ebay_fields_phase_a.py
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

TCG_CATEGORIES = ["pokemon_tcg", "one_piece_tcg", "gundam_tcg", "dragonball_scg", "yugioh_tcg"]

# category 別 eBay Game フィルタ正規値 (= 仮置き、 後で正規値調査結果に上書き可)
GAME_EBAY = {
    "pokemon_tcg": "Pokémon TCG",
    "one_piece_tcg": "One Piece TCG",
    "gundam_tcg": "Gundam Card Game",
    "dragonball_scg": "Dragon Ball Super Card Game",
    "yugioh_tcg": "Yu-Gi-Oh! TCG",
}

# category 別 language 推定 (= source 由来、 大半 Japanese)
# YGO は ygoprodeck EN base + Konami JA image → 個別 logic
LANGUAGE_DEFAULT = {
    "pokemon_tcg": "Japanese",
    "one_piece_tcg": "Japanese",
    "gundam_tcg": "Japanese",
    "dragonball_scg": "Japanese",
    "yugioh_tcg": "English",  # ygoprodeck base 英、 OCG variant は別途
}


def _extract_release_year(product_id: str, specs: dict, set_name_official: str) -> int | None:
    """release_year 推定 (= 既存 source data から)."""
    # 1. specs.year (= ShockBase 等で投入済)
    y = specs.get("year")
    if y:
        try:
            yi = int(y)
            if 1990 <= yi <= 2030:
                return yi
        except Exception:
            pass
    # 2. set_name_official に年度
    for s in (set_name_official or "", str(specs.get("set_name", ""))):
        m = re.search(r"(20\d{2})", s)
        if m:
            yi = int(m.group(1))
            if 1990 <= yi <= 2030:
                return yi
    # 3. product_id から OPCG / Gundam の set コード推定 (= 例 OP07 → 2024)
    m = re.match(r"^OP(\d+)", product_id)
    if m:
        op_n = int(m.group(1))
        # OP-01 = 2022, OP-02 = 2022, OP-03 = 2023, ..., OP-16 = 2026 (= 概算)
        return min(2022 + (op_n - 1) // 4, 2026)
    m = re.match(r"^FB(\d+)", product_id)
    if m:
        # FB01 = 2023, FB02 = 2023, ..., FB10 = 2026 (= 概算)
        return min(2023 + (int(m.group(1)) - 1) // 4, 2026)
    m = re.match(r"^GD(\d+)", product_id)
    if m:
        return min(2025 + (int(m.group(1)) - 1) // 4, 2026)  # GD01 = 2025
    return None


def _detect_language(category: str, product_id: str, specs: dict) -> str:
    """language 推定 (= category default + product_id pattern)."""
    # YGO: set_code に "JP" 含むなら JA、 そうでなければ EN
    if category == "yugioh_tcg":
        sc = specs.get("set_code", "") or ""
        if "JP" in sc or "JA" in sc:
            return "Japanese"
        if "EN" in sc or "DE" in sc or "FR" in sc or "IT" in sc or "SP" in sc:
            return "English"
        return "English"  # ygoprodeck base 想定
    return LANGUAGE_DEFAULT.get(category, "Japanese")


def process(dry_run: bool):
    print(f"=== TCG eBay Phase A ({'DRY-RUN' if dry_run else 'APPLY'}) ===")
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    grand = {"updated": 0, "release_year_filled": 0, "language_filled": 0}
    for cat in TCG_CATEGORIES:
        rs = db.execute(
            "SELECT id, product_id, specs, set_name_official FROM products WHERE category=?",
            (cat,),
        ).fetchall()
        n = len(rs)
        c = {"updated": 0, "year_added": 0, "lang_added": 0}
        for r in rs:
            try:
                specs = json.loads(r["specs"]) if r["specs"] else {}
            except Exception:
                specs = {}
            changed = False
            # card_size_ebay
            if "card_size_ebay" not in specs:
                specs["card_size_ebay"] = "Standard"
                changed = True
            # game_ebay
            if "game_ebay" not in specs:
                specs["game_ebay"] = GAME_EBAY.get(cat, "")
                changed = True
            # language
            if "language" not in specs:
                lang = _detect_language(cat, r["product_id"], specs)
                if lang:
                    specs["language"] = lang
                    c["lang_added"] += 1
                    changed = True
            # release_year
            if "release_year" not in specs:
                y = _extract_release_year(r["product_id"], specs, r["set_name_official"])
                if y:
                    specs["release_year"] = y
                    c["year_added"] += 1
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
        grand["updated"] += c["updated"]
        grand["release_year_filled"] += c["year_added"]
        grand["language_filled"] += c["lang_added"]
        print(f"  {cat:<22} {n:>6,} | updated={c['updated']:>5} "
              f"year+={c['year_added']:>5} lang+={c['lang_added']:>5}")
    db.close()
    print(f"\n=== grand ===")
    print(f"  total updated:    {grand['updated']:,}")
    print(f"  release_year +:   {grand['release_year_filled']:,}")
    print(f"  language +:       {grand['language_filled']:,}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--probe", action="store_true")
    args = p.parse_args()
    process(dry_run=args.probe)


if __name__ == "__main__":
    main()
