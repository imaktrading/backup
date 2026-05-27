"""既存 75 件 M-P entries を slash 形式に rename (SSOT 準拠).

依頼: 2026-05-27_sm_p_pokemon_promo_set_addition.md + SSOT 原則 + HQ Q3=C 並行実施

変換: M-P-NNN → NNN/M-P (= 公式 slash 形式)
冪等: 既に slash 形式の row があれば SKIP
"""
import sqlite3
import sys
import re
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

DB = "C:/dev/iMak_data/catalog/products.sqlite"
NOW = datetime.now().isoformat()


def main():
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    cur = db.cursor()

    rows = cur.execute(
        "SELECT id, product_id, name FROM products "
        "WHERE category='pokemon_tcg' AND product_id LIKE 'M-P-%' "
        "ORDER BY product_id"
    ).fetchall()

    print(f"対象 row count: {len(rows)}")

    renamed = 0
    skipped = 0
    collisions = 0

    for r in rows:
        old_pid = r["product_id"]
        m = re.match(r"^M-P-(\d+)$", old_pid)
        if not m:
            print(f"  SKIP (regex mismatch): {old_pid}")
            skipped += 1
            continue
        num = m.group(1)
        new_pid = f"{num}/M-P"

        # 衝突確認
        existing_slash = cur.execute(
            "SELECT id FROM products WHERE category='pokemon_tcg' AND product_id=?",
            (new_pid,),
        ).fetchone()
        if existing_slash:
            print(f"  COLLISION: {old_pid} → {new_pid} (= slash row 既存 id={existing_slash['id']})")
            collisions += 1
            continue

        cur.execute(
            "UPDATE products SET product_id=?, updated_at=? WHERE id=?",
            (new_pid, NOW, r["id"]),
        )
        print(f"  RENAME: {old_pid} → {new_pid}  | {r['name'][:30] if r['name'] else ''}")
        renamed += 1

    db.commit()
    db.close()

    print(f"\n=== 集計 ===")
    print(f"  RENAMED:    {renamed}")
    print(f"  SKIPPED:    {skipped}")
    print(f"  COLLISIONS: {collisions}")


if __name__ == "__main__":
    main()
