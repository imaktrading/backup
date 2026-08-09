"""FB07-097 神龍 (Shenron) 系 4件に name_en='Shenron' を投入.

依頼: requests/psa_preflight_report_response.md §3 (G7 SHENRON name_en 補完)

真因: FB07-097 / _p1 / _p2 / _p3 は name_en=None のため PSA subject
"SHENRON ALTERNATE ART #FB07-097" が _record_name_matches_subject の
combined(name+name_en+name_jp)='神龍  神龍' に 'SHENRON' token を見出せず
false → recovery reject (=set_code=None として preflight GAP 計上)。

公式英語名 = "Shenron" (Fusion World 英語公式 dbs-cardgame.com/fw/en/
cardlist/detail.php?card_no=FB07-097 で本文<h1 class='cardName is-back'>
Shenron</h1> を実確認済 = 2026-08-09)。fail-closed 範囲内(推測でない)。

対象: category=dragonball_scg / product_id ∈ {FB07-097, _p1, _p2, _p3}
のうち name_en IS NULL or '' のもの。dummy_s1 / SB02 系(name='Dragon Ball'
= 表面) は本 GAP スコープ外 (別 audit)。
"""
import sqlite3
import sys
from datetime import datetime, timezone

DB = 'C:/dev/iMak_data/catalog/products.sqlite'
STAMP = '20260809'
BAK = f'{DB}.bak_{STAMP}_shenron_nameen'

TARGET_PIDS = ('FB07-097', 'FB07-097_p1', 'FB07-097_p2', 'FB07-097_p3')


def run(apply=False):
    import shutil
    now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S')
    if apply:
        shutil.copy2(DB, BAK); print(f'[backup] {BAK}')
    c = sqlite3.connect(DB); cur = c.cursor()
    placeholders = ','.join('?' for _ in TARGET_PIDS)
    cur.execute(
        f"SELECT COUNT(*) FROM products WHERE category='dragonball_scg' "
        f"AND product_id IN ({placeholders}) AND (name_en IS NULL OR name_en='')",
        TARGET_PIDS,
    )
    n = cur.fetchone()[0]
    if apply:
        cur.execute(
            f"UPDATE products SET name_en='Shenron', name_en_source='dbfw_en_official', "
            f"updated_at=? WHERE category='dragonball_scg' "
            f"AND product_id IN ({placeholders}) AND (name_en IS NULL OR name_en='')",
            (now, *TARGET_PIDS),
        )
        c.commit()
    print(f"{'APPLIED' if apply else 'DRYRUN'}: name_en='Shenron' set for {n} entries")


if __name__ == '__main__':
    run(apply='--apply' in sys.argv)
