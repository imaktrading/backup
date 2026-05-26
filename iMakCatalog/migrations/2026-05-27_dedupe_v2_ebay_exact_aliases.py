"""dedupe Phase 1i v2 alias 修正: ebay_value を eBay set aspect 実値完全一致に揃える.

依頼: C:/dev/iMak_data/catalog/requests/2026-05-27_dedupe_unmapped_sets_v2_alias_correction.md
前提: dedupe `catalog_io.py` は `WHERE field='set_code' AND ebay_value=<eBay aspect>` で逆引き
      v1 で投入した field='set' alias 行は chain しないため機能せず → set_code 行の
      ebay_value を eBay 実値に直接合わせる方針。

注意点:
- set_code 行は UNIQUE(category, field, source_value) で 1 set_code = 1 ebay_value のみ
- 「canonical 名」は v1 時点で placeholder だったので失っても損失少
- 元 ebay_value は note に併記して履歴保存
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
NOTE_TAG = "; dedupe v2 2026-05-27 eBay 実値修正"

# (category, set_code (source_value), new ebay_value, extra_note)
UPDATES = [
    ("pokemon_tcg", "SM12a", "Sun & Moon Tag Team Gx All Stars",
     "v1 'Tag Team GX All Stars' (placeholder canonical) → eBay set aspect 実値"),
    ("pokemon_tcg", "SM11a", "Sun & Moon Remix Bout",
     "v1 'Remix Bout' → eBay set aspect 実値"),
    ("pokemon_tcg", "S10b", "Go Japanese",
     "v1 'Pokémon GO' → eBay set aspect 実値 (= 'Go Japanese' 表記、 dedupe 観察)"),
]

# 新規 set_code 行 (= eBay aspect が catalog 既存 set_code に紐付かないパターン)
INSERTS = [
    # Edition Beta Promos: catalog product_id pattern GD01-NNN_BETA_ENG (42 件)
    # virtual set_code 'GD-BETA' で dedupe 側マッチ可能化
    ("gundam_tcg", "set_code", "GD-BETA", "Edition Beta Promos",
     "virtual set_code; catalog product_id GD01-NNN_BETA_ENG パターン (42 件) を集約。 dedupe で eBay set aspect 'Edition Beta Promos' 逆引き用"),

    # Gundam Japanese Resource: catalog products 未投入
    # virtual set_code 'GD-RES' で eBay aspect 認識のみ可能化 (= 復元は catalog scrape 後)
    ("gundam_tcg", "set_code", "GD-RES", "Gundam Japanese Resource",
     "virtual set_code; Resource Card 系は catalog 未投入、 別 phase で scrape 必要。 eBay aspect 認識のみ"),

    # Sword & Shield Start Deck 100 Corocoro Comics Promotion: catalog 's1a' は 'VMAX Rising' (= 別 set)
    # 公式 Start Deck 100 set_code は 'SI' (Pokemon TCG) ? 確定不明、 virtual 's1-CORO' で代用
    ("pokemon_tcg", "set_code", "s1-CORO", "Sword & Shield Start Deck 100 Corocoro Comics Promotion",
     "virtual set_code; Sword & Shield Start Deck 100 + Corocoro promo 系。 catalog 未投入、 後日 scrape 後 set_code 修正推奨"),
]


def main():
    db = sqlite3.connect(DB)
    cur = db.cursor()

    updated = 0
    inserted = 0
    skipped = 0

    print("=== UPDATEs ===")
    for cat, src, new_eb, why in UPDATES:
        existing = cur.execute(
            "SELECT id, ebay_value, note FROM ebay_filter_map WHERE category=? AND field='set_code' AND source_value=?",
            (cat, src),
        ).fetchone()
        if not existing:
            print(f"  WARN: {cat}/set_code/{src!r} not found, skipping UPDATE")
            skipped += 1
            continue
        ex_id, ex_ebay, ex_note = existing
        if ex_ebay == new_eb:
            print(f"  SKIP (既に一致): {cat}/set_code/{src!r} = {new_eb!r}")
            skipped += 1
            continue
        merged_note = f"{ex_note}; {why}{NOTE_TAG}"
        cur.execute(
            "UPDATE ebay_filter_map SET ebay_value=?, note=? WHERE id=?",
            (new_eb, merged_note, ex_id),
        )
        print(f"  UPDATE: {cat}/set_code/{src!r}  {ex_ebay!r} → {new_eb!r}")
        updated += 1

    print("\n=== INSERTs ===")
    for cat, field, src, eb, note in INSERTS:
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
                merged_note = f"{note}{NOTE_TAG}; 旧 ebay_value={ex_ebay!r}"
                cur.execute(
                    "UPDATE ebay_filter_map SET ebay_value=?, note=? WHERE id=?",
                    (eb, merged_note, ex_id),
                )
                print(f"  UPDATE (existed): {cat}/{field}/{src!r}  {ex_ebay!r} → {eb!r}")
                updated += 1
            continue
        cur.execute(
            "INSERT INTO ebay_filter_map (category, field, source_value, ebay_value, note, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (cat, field, src, eb, note + NOTE_TAG, NOW),
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
