"""DragonBall Energy Marker に name_en='Energy Marker' を投入.

依頼: requests/2026-06-11_psa_preflight_full_audit_indexfail_and_gaps.md (GAP)。
ENERGY MARKER alt-art ~23 cert が GAP 判定だが、catalog に E01-* / E-* で実在。
真因: name_en=None のため PSA subject「ENERGY MARKER」が _record_name_matches_subject
で照合できず reject(=未収録に誤判定)。name_en を入れれば照合通過し RESOLVED 化。

公式英語名 = "Energy Marker"(DBSCG 公式タームの直訳。エナジーマーカー)。fail-closed 範囲内
(推測でなく確定訳)。
"""
import sqlite3, sys
from datetime import datetime, timezone

DB = 'C:/dev/iMak_data/catalog/products.sqlite'
STAMP = '20260611'
BAK = f'{DB}.bak_{STAMP}_energymarker_nameen'


def run(apply=False):
    import shutil
    now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S')
    if apply:
        shutil.copy2(DB, BAK); print(f'[backup] {BAK}')
    c = sqlite3.connect(DB); cur = c.cursor()
    cur.execute(
        "SELECT COUNT(*) FROM products WHERE category='dragonball_scg' "
        "AND name_jp='エナジーマーカー' AND (name_en IS NULL OR name_en='')")
    n = cur.fetchone()[0]
    if apply:
        cur.execute(
            "UPDATE products SET name_en='Energy Marker', name_en_source='official_term', "
            "updated_at=? WHERE category='dragonball_scg' AND name_jp='エナジーマーカー' "
            "AND (name_en IS NULL OR name_en='')", (now,))
        c.commit()
    print(f"{'APPLIED' if apply else 'DRYRUN'}: name_en='Energy Marker' set for {n} entries")


if __name__ == '__main__':
    run(apply='--apply' in sys.argv)
