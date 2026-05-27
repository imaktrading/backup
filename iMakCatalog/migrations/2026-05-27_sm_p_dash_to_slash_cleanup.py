"""SM-P 系 旧 'SMP-NNN' (dash) entries を slash 'NNN/SM-P' 形式に統合 cleanup.

背景:
- 旧 derive_product_id は '{set_code}-{card_number}' = 'SMP-NNN' を出力していた
- 今日 SSOT 準拠で slash 形式 '{card_number}/{promo_code}' = 'NNN/SM-P' に修正
- 新 scrape で 141 件 slash 形式 INSERT、 旧 'SMP-NNN' は残置 = 二重登録

cleanup:
1. 各 'SMP-NNN' entry に対応する slash 'NNN/SM-P' があれば: 旧 'SMP-NNN' DELETE (= 新 entry が完全形)
2. 対応 slash がない (= 今日 scrape されなかった entry): UPDATE で pid を 'NNN/SM-P' に rename

冪等: 再実行で全 'SMP-NNN' が消えるまで安全.
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
        "SELECT id, product_id, source_url FROM products "
        "WHERE category='pokemon_tcg' AND product_id LIKE 'SMP-%' "
        "ORDER BY product_id"
    ).fetchall()

    print(f"対象 'SMP-NNN' entries: {len(rows)}")

    deleted_dup = 0
    renamed = 0
    skipped = 0

    for r in rows:
        old_pid = r["product_id"]
        m = re.match(r"^SMP-(\d+)$", old_pid)
        if not m:
            print(f"  SKIP (regex mismatch): {old_pid}")
            skipped += 1
            continue
        num = m.group(1)
        new_pid = f"{num}/SM-P"

        # 同じ slash 形式 entry が既に存在するか
        existing_slash = cur.execute(
            "SELECT id FROM products WHERE category='pokemon_tcg' AND product_id=?",
            (new_pid,),
        ).fetchone()

        if existing_slash:
            # 二重登録 — 古い 'SMP-NNN' を削除 (新 slash entry が今日の scrape で完全形)
            cur.execute("DELETE FROM products WHERE id=?", (r["id"],))
            print(f"  DELETE dup: {old_pid} (id={r['id']}) ← slash {new_pid} (id={existing_slash['id']}) 存在")
            deleted_dup += 1
        else:
            # slash 形式なし → rename
            cur.execute(
                "UPDATE products SET product_id=?, updated_at=? WHERE id=?",
                (new_pid, NOW, r["id"]),
            )
            print(f"  RENAME: {old_pid} → {new_pid}")
            renamed += 1

    db.commit()

    # 最終状態確認
    n_slash = cur.execute(
        "SELECT COUNT(*) FROM products WHERE category='pokemon_tcg' AND product_id LIKE '%/SM-P'"
    ).fetchone()[0]
    n_dash_remain = cur.execute(
        "SELECT COUNT(*) FROM products WHERE category='pokemon_tcg' AND product_id LIKE 'SMP-%'"
    ).fetchone()[0]
    db.close()

    print(f"\n=== 集計 ===")
    print(f"  DELETE 重複: {deleted_dup}")
    print(f"  RENAME 新規: {renamed}")
    print(f"  SKIP:        {skipped}")
    print()
    print(f"  最終 SM-P (slash) entries: {n_slash}")
    print(f"  残 SMP-* (dash) entries:  {n_dash_remain} (0 期待)")


if __name__ == "__main__":
    main()
