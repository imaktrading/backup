"""name_en 散発誤り 32件 (item/trainer, Durant型番号オフセットの残) を確定値に訂正.

HQ依頼: requests/2026-06-08_name_en_tier3_singlecard_errors_32.md
species でなく item/trainer(pokeapi対象外でdisputed検出を逃れた)の少数派誤り。
各 name_jp は英名一意(name_jp直訳でクロスチェック済)。訂正→verified_manual昇格。

実行: python iMakCatalog/migrations/2026-06-08_pokemon_name_en_tier3_singlecard_fix.py [--commit]
"""
from __future__ import annotations
import argparse, shutil, sqlite3, sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import api  # noqa: E402
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
DB_PATH = Path(api._DB_PATH)
NOW = datetime.now().isoformat()
SRC_TAG = "hq_confirmed_tier3_singlecard_20260608"

# product_id -> (確定 name_en, name_jp参考)
FIX = {
    "SA-012": "Energy Retrieval", "DPs-S-009": "Energy Switch", "MG-009": "Energy Switch",
    "SA-013": "Energy Search", "SA-015": "Pokégear 3.0", "SA-016": "Switch",
    "SA-017": "Pokémon Catcher", "DPs-S-011": "Poké Ball", "006/M-P": "Counter Gain",
    "007/M-P": "Lillie's Determination", "023/M-P": "Basic Grass Energy",
    "013/M-P": "Basic Psychic Energy", "014/M-P": "Basic Fighting Energy",
    "015/M-P": "Basic Darkness Energy", "016/M-P": "Basic Metal Energy",
    "008/M-P": "Mega Signal", "XY-014": "Super Rod", "SCS-018": "Professor's Research",
    "SA-019": "Vitality Band", "XY-029": "Level Ball", "SCS-019": "Imitation Pokémon",
    "SA-022": "Imitation Pokémon", "XY-025": "Battle Compressor",
    "XY-026": "Battle Searcher", "XY-020": "Battle Searcher", "XY-031": "Muscle Band",
    "XY-037": "Blacksmith", "XY-038": "Korrina", "XY-044": "Strong Energy",
    "XY-045": "Double Dragon Energy", "065/M-P": "Double Dragon Energy",
    "DPs-S-012": "Warp Point",
}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()
    con = sqlite3.connect(str(DB_PATH)); con.row_factory = sqlite3.Row; cur = con.cursor()
    targets = []
    missing = []
    for code, new in FIX.items():
        r = cur.execute(
            "SELECT id, name_jp, name_en FROM products WHERE category='pokemon_tcg' AND product_id=?",
            (code,)).fetchone()
        if not r:
            missing.append(code); continue
        targets.append((r["id"], code, r["name_jp"], r["name_en"], new))
    for rid, code, jp, old, new in targets:
        print(f"   {code:12} {jp!r:14} {old!r:24} -> {new!r}")
    if missing:
        print(f"  ⚠️ 未検出 product_id: {missing}")
    print(f"\n  対象 {len(targets)} / {len(FIX)} 件")

    if not args.commit:
        print("\n  (DRY-RUN: --commit で適用)"); con.close(); return

    shutil.copy2(DB_PATH, DB_PATH.with_name(
        DB_PATH.name + ".pre_tier3single_" + datetime.now().strftime("%Y%m%d_%H%M%S")))
    for rid, code, jp, old, new in targets:
        cur.execute("UPDATE products SET name_en=?, name_en_source=?, updated_at=? WHERE id=?",
                    (new, SRC_TAG, NOW, rid))
        cur.execute(
            "INSERT INTO b_layer_status (product_id_ref, category, product_code, field, status, oracle, checked_at, note) "
            "VALUES (?, 'pokemon_tcg', ?, 'name_en', 'verified_manual', ?, ?, ?) "
            "ON CONFLICT(product_id_ref, field) DO UPDATE SET status='verified_manual', "
            "oracle=excluded.oracle, checked_at=excluded.checked_at, note=excluded.note",
            (rid, code, SRC_TAG, NOW, f"tier3 single fixed from {old!r}"))
    con.commit()
    print(f"\n  ✅ name_en 訂正 + verified_manual: {len(targets)} 件"); con.close()


if __name__ == "__main__":
    main()
