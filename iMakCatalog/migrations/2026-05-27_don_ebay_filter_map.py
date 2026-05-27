"""DON Card eBay filter map (= dedupe Set aspect 逆引き用).

依頼: 2026-05-27_don_card_set_investment.md Phase 2

dedupe cache に DON aspect sample なし (= 97 listings 内 hit 0)、
eBay 一般慣行に基づく alias 投入. 実際の eBay aspect 値は後日 dedupe 観察で
確認 + alias 追補可能.

採用 convention:
  field='set_code': source_value='DON' (= 内部 KEY), ebay_value=<eBay set aspect>
  field='set':       source_value=<eBay alias variants>, ebay_value='DON Card' (canonical)
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
NOTE_TAG = "; DON Card 2026-05-27"

UPSERTS = [
    # set_code 内部 KEY 'DON' で eBay aspect を逆引きできるよう双方向 row 投入
    ("one_piece_tcg", "set_code", "DON", "DON Card",
     "DON カード総称 prefix (= catalog product_id 'DON-{set_code}-NNN' に対応); eBay set aspect 逆引き用" + NOTE_TAG),

    # eBay aspect 表記揺れ alias (= eBay 観察未済、 一般慣行ベース)
    ("one_piece_tcg", "set", "DON Card", "DON Card",
     "self-alias (= dedupe 逆引き保険)" + NOTE_TAG),
    ("one_piece_tcg", "set", "DON!! Card", "DON Card",
     "eBay aspect alias (= !! 付き表記)" + NOTE_TAG),
    ("one_piece_tcg", "set", "DON", "DON Card",
     "eBay aspect alias (= 短縮)" + NOTE_TAG),
    ("one_piece_tcg", "set", "Don Card", "DON Card",
     "eBay aspect alias (= title case)" + NOTE_TAG),
    ("one_piece_tcg", "set", "DON!!", "DON Card",
     "eBay aspect alias" + NOTE_TAG),
    ("one_piece_tcg", "set", "ドンカード", "DON Card",
     "eBay aspect alias (= 日本語)" + NOTE_TAG),
    ("one_piece_tcg", "set", "ドン!!カード", "DON Card",
     "eBay aspect alias (= 日本語 !! 付き)" + NOTE_TAG),
]


def main():
    db = sqlite3.connect(DB)
    cur = db.cursor()

    inserted = 0
    updated = 0
    skipped = 0

    for cat, field, src, eb, note in UPSERTS:
        existing = cur.execute(
            "SELECT id, ebay_value FROM ebay_filter_map WHERE category=? AND field=? AND source_value=?",
            (cat, field, src),
        ).fetchone()

        if existing:
            ex_id, ex_ebay = existing
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
