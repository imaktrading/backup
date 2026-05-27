"""products table に `variants` JSON 列追加 (= variant Phase A 案 A schema migration).

依頼: 2026-05-27_catalog_variant_meta_phase_a_implementation.md
案 A: products に variants JSON 列追加 (= 既存 specs JSON pattern と一貫)

冪等: 既に列存在なら SKIP
"""
import sqlite3
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

DB = "C:/dev/iMak_data/catalog/products.sqlite"


def main():
    db = sqlite3.connect(DB)
    cur = db.cursor()

    # 既存 columns 確認
    cols = [c[1] for c in cur.execute("PRAGMA table_info(products)").fetchall()]
    if "variants" in cols:
        print("  SKIP: variants 列 既存")
        return

    cur.execute("ALTER TABLE products ADD COLUMN variants TEXT")
    db.commit()
    print("  ADDED: products.variants TEXT (= JSON、 NULL 許容)")

    # 確認
    cols2 = [c[1] for c in cur.execute("PRAGMA table_info(products)").fetchall()]
    print(f"  current columns: {cols2}")
    db.close()


if __name__ == "__main__":
    main()
