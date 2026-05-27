"""G-shock 92 models 投入後の band_color heuristic 例外を明示 override.

依頼: 2026-05-27_catalog_gshock_models_addition_implementation.md (= 92 models 投入の後処理)

背景:
- 投入 92 models のうち 11 entries で band_color 公式値 != heuristic 推測値
- 例: GBD-800UC-8 公式 Orange (Casio 公式 scrape 値) vs heuristic 'Silver' (= suffix 8 → Silver)
- これらは Casio が非慣行 color combo を採用した legitimate な例外
- 既存 catalog 整合性 test (= test_all_band_colors_consistent) が detect

対応:
- 該当 11 entries の specs に `band_color_source='hq_confirmed'` 追加
- = 「heuristic と異なるが Casio 公式 scrape で確認済」 明示 override
"""
import sqlite3
import sys
import json
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

DB = "C:/dev/iMak_data/catalog/products.sqlite"
NOW = datetime.now().isoformat()

# heuristic mismatch entries (= test_all_band_colors_consistent 検出分)
TARGETS = [
    "GBD-200",            # 'Black' vs 'Blue' (suffix なし、 ambiguous)
    "G-5600BG-5JR",       # 'White' vs 'Beige'
    "GBD-800UC-5",        # 'White' vs 'Beige'
    "GBD-800UC-8",        # 'Orange' vs 'Silver'
    "GBX-100-8JF",        # 'Orange' vs 'Silver'
    "GD-010CE-5JF",       # 'White' vs 'Beige'
    "GD-B500MW-8JF",      # 'Orange' vs 'Silver'
    "GM-2100",            # 'Black' vs 'Blue' (suffix なし)
    "GM-2100YM-8AJF",     # 'Orange' vs 'Silver'
    "GM-2100YRA-8AJF",    # 'Orange' vs 'Silver'
    "GM-5600YRA-8JF",     # 'Orange' vs 'Silver'
]


def main():
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    cur = db.cursor()

    updated = 0
    not_found = []
    for pid in TARGETS:
        r = cur.execute(
            "SELECT id, specs FROM products WHERE category='gshock' AND product_id=?",
            (pid,),
        ).fetchone()
        if not r:
            not_found.append(pid)
            continue
        try:
            specs = json.loads(r["specs"])
        except Exception:
            specs = {}
        cat_color = specs.get("band_color", "")
        specs["band_color_source"] = "hq_confirmed"
        specs["band_color_note"] = (
            f"Casio 公式 scrape 値 '{cat_color}'、 heuristic suffix-color と異なるが公式値が正"
        )
        cur.execute(
            "UPDATE products SET specs=?, updated_at=? WHERE id=?",
            (json.dumps(specs, ensure_ascii=False), NOW, r["id"]),
        )
        print(f"  override: {pid} band_color={cat_color!r} (source→ hq_confirmed)")
        updated += 1

    db.commit()
    db.close()

    print(f"\n=== 集計 ===")
    print(f"  UPDATE: {updated}")
    if not_found:
        print(f"  NOT FOUND: {len(not_found)} = {not_found}")


if __name__ == "__main__":
    main()
