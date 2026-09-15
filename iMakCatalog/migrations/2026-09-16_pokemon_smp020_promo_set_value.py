"""SM-P-020 (ハウ) の set_name_ebay を英語版の基本セット名から プロモの値に直す — 2026-09-16

9/15 に日本語版の旧セット 1,643行を直した時の残り 1行。
この行だけ `set_name_official` が `拡張パック「サン&ムーン」` (半角 &) で、他の弾の表に無く、
英語版の基本セット `Sun & Moon` が焼かれていた。product_id は `SM-P-020` = **プロモ**なので、
変換表から引き直すと `Sm-P: Sun & Moon Promos` (eBay master に在る値) になる。

- 今の値が `Sun & Moon` の行だけ書く
- 書く値は `api.derive_set_name_ebay` が返す値と一致することを確かめてから書く

実行:
    python migrations/2026-09-16_pokemon_smp020_promo_set_value.py            # dry-run
    python migrations/2026-09-16_pokemon_smp020_promo_set_value.py --commit
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import api  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PID = "SM-P-020"
OLD = "Sun & Moon"


def main(commit: bool) -> None:
    db = sqlite3.connect(api._DB_PATH, timeout=120)
    row = db.execute("SELECT id, set_name_official, specs FROM products "
                     "WHERE category='pokemon_tcg' AND product_id=?", (PID,)).fetchone()
    if not row:
        print(f"{PID} が無い")
        return
    rid, son, sp = row
    s = json.loads(sp or "{}")
    derived = api.derive_set_name_ebay("pokemon_tcg", son, PID)
    print(f"  {PID}: 今 {s.get('set_name_ebay')!r} → 変換表 {derived!r}")
    if s.get("set_name_ebay") != OLD or not derived:
        print("  想定と違うので書かない")
        return
    if commit:
        now = datetime.now().isoformat(timespec="seconds")
        s["set_name_ebay"] = derived
        s["set_name_ebay_source"] = "jp_old_set_own_value_20260916"
        s["set_name_ebay_prev"] = OLD
        db.execute("UPDATE products SET specs=?, updated_at=? WHERE id=?",
                   (json.dumps(s, ensure_ascii=False), now, rid))
        db.commit()
    left = db.execute("SELECT count(*) FROM products WHERE category='pokemon_tcg' "
                      "AND json_extract(specs,'$.set_name_ebay')=?", (OLD,)).fetchone()[0]
    print(f"  英語版の基本セット名の残り {left}行 / {'commit' if commit else 'dry-run'}")


if __name__ == "__main__":
    main("--commit" in sys.argv)
