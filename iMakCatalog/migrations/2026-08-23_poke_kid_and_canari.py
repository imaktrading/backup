"""ポケモンごっこ -> Poké Kid / カナリィ -> Canari (直訳が英名に入っていた 10行).

依頼: requests/2026-08-23_hq_translated_names_pokekid_canari.md (判定①)

## 根拠 (2026-08-23 に PSA 実物をその場で取得)

    cert 144091892  Brand=POKEMON JAPANESE SWORD & SHIELD SHINY STAR V / #197
                    Subject = "FA/POKE KID"        -> S4a-197 は Poké Kid
    cert 146303999  Brand=POKEMON JAPANESE M2a-MEGA DREAM ex / #219
                    Subject = "CANARI"             -> M2a-219 は Canari

## 直すもの

    ポケモンごっこ 7行  'Imitation Pokémon' -> 'Poké Kid'
        S-P-057 S4a-197 SA-022 SC2-018 SCS-019 SD-115 SP1-006
        (S8a-G-014 は既に 'Poké Kid'。カタログ内で割れていた)
    カナリィ 3行        'Canary' -> 'Canari'
        M2a-170 M2a-219 M2a-248

`name_en` と `specs.character_name` の両方。eBay の C:Character は character_name 由来。

★名前で一括置換しない。**日本語名で対象を絞る** (Jacq の時に、同じ英名 Zinnia を持つ
  「ヒガナ」2行を巻き込みかけた)。

実行:
  python migrations/2026-08-23_poke_kid_and_canari.py           # dry-run
  python migrations/2026-08-23_poke_kid_and_canari.py --commit
"""
from __future__ import annotations

import argparse
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

NOW = datetime.now().isoformat(timespec="seconds")
SOURCE = "psa_slab_confirmed_20260823"

# 日本語名 -> (誤った英名, 正しい英名, 根拠 cert)
FIX = {
    "ポケモンごっこ": ("Imitation Pokémon", "Poké Kid", "cert144091892"),
    "カナリィ":     ("Canary",            "Canari",   "cert146303999"),
}


def run(commit: bool) -> None:
    db = sqlite3.connect(Path(api._DB_PATH))
    db.row_factory = sqlite3.Row
    n = 0
    for jp, (wrong, right, cert) in FIX.items():
        rows = db.execute(
            "SELECT id, product_id, name, name_en, specs FROM products "
            "WHERE category='pokemon_tcg' AND name=?", (jp,)).fetchall()
        print(f"■ {jp}  ({len(rows)} 行)  {wrong!r} -> {right!r}   根拠 {cert}")
        for r in rows:
            s = json.loads(r["specs"] or "{}")
            if r["name_en"] == right and s.get("character_name") == right:
                print(f"    - {r['product_id']:12s} 既に {right} → skip")
                continue
            print(f"    + {r['product_id']:12s} {r['name_en']!r} / "
                  f"char={s.get('character_name')!r} -> {right!r}")
            s["character_name"] = right
            s["name_en_fix"] = f"2026-08-23_{cert}"
            n += 1
            if commit:
                db.execute(
                    "UPDATE products SET name_en=?, name_en_source=?, specs=?, "
                    "updated_at=? WHERE id=?",
                    (right, SOURCE, json.dumps(s, ensure_ascii=False), NOW, r["id"]))
    if commit:
        db.commit()
        print(f"\n[OK] 適用 {n} 行")
    else:
        print(f"\n対象 {n} 行 (dry-run — --commit で適用)")
    db.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--commit", action="store_true")
    run(p.parse_args().commit)
