"""ドラゴンボールの変換表から、公式に無い誤字の見出し2行を DB からも消す — 2026-09-15

週次の整合性チェック (2026-09-14) §4 未検証map / §5 map潰れ に出ていた:

    ブースターパック 迫り高き戦闘力 [FB08] -> Saiyan's Pride   (公式は「誇り高き戦闘民族」)
    ブースターパック 迫り来る強敵[FB06]    -> Rivals Clash     (公式は「迫り来る脅威」)

products にこの名前の行は 0件 (どこからも引かれていない誤字)。YAML からは同日削除した。
`ebay_filter_map/loader.py` は upsert だけで消さないので、DB の ebay_filter_map からここで消す。

実行:
    python migrations/2026-09-15_dragonball_filter_map_drop_typo_sources.py            # dry-run
    python migrations/2026-09-15_dragonball_filter_map_drop_typo_sources.py --commit
"""
from __future__ import annotations

import sqlite3
import sys

DB = "C:/dev/iMak_data/catalog/products.sqlite"
TYPO = ("ブースターパック 迫り高き戦闘力 [FB08]", "ブースターパック 迫り来る強敵[FB06]")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def main(commit: bool) -> None:
    db = sqlite3.connect(DB, timeout=120)
    q = ("FROM ebay_filter_map WHERE category='dragonball_scg' AND field='set' "
         f"AND source_value IN ({','.join('?' * len(TYPO))})")
    used = db.execute(f"SELECT count(*) FROM products WHERE set_name_official IN ({','.join('?' * len(TYPO))})",
                      TYPO).fetchone()[0]
    if used:
        print(f"この名前を使う行が {used}件ある — 消さずに止める")
        return
    n = db.execute("SELECT count(*) " + q, TYPO).fetchone()[0]
    if commit:
        db.execute("DELETE " + q, TYPO)
        db.commit()
    left = db.execute("SELECT count(*) " + q, TYPO).fetchone()[0]
    print(f"対象 {n}行 / 残り {left}行 / {'commit' if commit else 'dry-run'}")


if __name__ == "__main__":
    main("--commit" in sys.argv)
