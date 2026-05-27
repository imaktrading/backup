"""ebay_filter_map に SM-P + M-P 行を追加 (= dedupe Set aspect 逆引き用).

依頼:
  - 2026-05-27_sm_p_pokemon_promo_set_addition.md
  - HQ SSOT 原則準拠 (= ebay_value は eBay 実表示完全一致)

eBay aspect 実値 (dedupe cache `listing_specs_2026-05-27.json` から):
  - SM-P: 'Sm Promo' (確認済)
  - M-P : (未確認、 v1 で投入済の 'Japanese Promo' に加え汎用 alias 追加)
"""
import sqlite3
import sys
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

DB = "C:/dev/iMak_data/catalog/products.sqlite"
NOW = datetime.now().isoformat()
NOTE_TAG = "; dedupe SM-P + M-P 2026-05-27"

# (category, field, source_value, ebay_value, note)
UPSERTS = [
    # ----- SM-P (Sun & Moon Promo) -----
    # dedupe 逆引き: WHERE field='set_code' AND ebay_value='Sm Promo' → source_value='SM-P'
    ("pokemon_tcg", "set_code", "SM-P", "Sm Promo",
     "Sun & Moon Promo prefix; catalog product_id NNN/SM-P 形式と整合; dedupe cache 'Sm Promo' 確認済" + NOTE_TAG),

    # forward 補助 (= alias 行、 表記揺れ対応)
    ("pokemon_tcg", "set", "Sun & Moon Promo", "Sm Promo",
     "eBay aspect 表記揺れ alias" + NOTE_TAG),
    ("pokemon_tcg", "set", "Sun and Moon Promo", "Sm Promo",
     "eBay aspect 表記揺れ alias" + NOTE_TAG),
    ("pokemon_tcg", "set", "SM Promo", "Sm Promo",
     "eBay aspect 表記揺れ alias (case fold)" + NOTE_TAG),

    # ----- M-P (Mega Promo) -----
    # 既存 v1 で投入済 ('M-P' → 'Japanese Promo'). HQ Q3=C で M-P entries 全件 slash 化に伴い、
    # ebay_value を SM-P と同 pattern の 公式風 'M Promo' or 'Mega Promo' に併設.
    # 既存 'Japanese Promo' は保持、 追加 alias で eBay 表記揺れ吸収.
    ("pokemon_tcg", "set", "Mega Promo", "Japanese Promo",
     "eBay aspect alias (M-P = Mega Evolution Promo era)" + NOTE_TAG),
    ("pokemon_tcg", "set", "M Promo", "Japanese Promo",
     "eBay aspect alias (M-P 略称)" + NOTE_TAG),
    ("pokemon_tcg", "set", "Pokemon Mega Promo", "Japanese Promo",
     "eBay aspect alias" + NOTE_TAG),
]


def main():
    db = sqlite3.connect(DB)
    cur = db.cursor()

    inserted = 0
    updated = 0
    skipped = 0

    for cat, field, src, eb, note in UPSERTS:
        existing = cur.execute(
            "SELECT id, ebay_value, note FROM ebay_filter_map WHERE category=? AND field=? AND source_value=?",
            (cat, field, src),
        ).fetchone()

        if existing:
            ex_id, ex_ebay, ex_note = existing
            if ex_ebay == eb:
                print(f"  SKIP (既存一致): {cat}/{field}/{src!r} → {eb!r}")
                skipped += 1
            else:
                merged_note = f"{note}; 旧 ebay_value={ex_ebay!r}"
                cur.execute(
                    "UPDATE ebay_filter_map SET ebay_value=?, note=? WHERE id=?",
                    (eb, merged_note, ex_id),
                )
                print(f"  UPDATE: {cat}/{field}/{src!r}  {ex_ebay!r} → {eb!r}")
                updated += 1
        else:
            cur.execute(
                "INSERT INTO ebay_filter_map (category, field, source_value, ebay_value, note, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (cat, field, src, eb, note, NOW),
            )
            print(f"  INSERT: {cat}/{field}/{src!r} → {eb!r}")
            inserted += 1

    db.commit()
    db.close()

    print(f"\n=== 集計 ===")
    print(f"  INSERT: {inserted}")
    print(f"  UPDATE: {updated}")
    print(f"  SKIP:   {skipped}")


if __name__ == "__main__":
    main()
