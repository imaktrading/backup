"""ポケモンごっこ = Poké Kid / カナリィ = Canari を固定する (直訳が英名に入っていた).

根拠 (2026-08-23 に PSA 実物をその場で取得):
    cert 144091892  SWORD & SHIELD SHINY STAR V #197  Subject = "FA/POKE KID"
    cert 146303999  M2a-MEGA DREAM ex #219            Subject = "CANARI"

★カナリィは **カタログ内では割れていなかった** (3行とも 'Canary')。
  「同じ日本語名に英名が2つある」検出では捕まらない型。PSA ラベルとの突合でしか出ない。
"""
from __future__ import annotations

import json
import sqlite3
import sys
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))
import api  # type: ignore  # noqa: E402

WANT = {"ポケモンごっこ": "Poké Kid", "カナリィ": "Canari"}
FORBIDDEN = {"Imitation Pokémon", "Make-believe Pokémon", "Canary"}


def _rows(jp):
    db = sqlite3.connect(str(api._DB_PATH))
    try:
        return db.execute(
            "SELECT product_id, name_en, specs FROM products "
            "WHERE category='pokemon_tcg' AND name=?", (jp,)).fetchall()
    finally:
        db.close()


class TestNames(unittest.TestCase):
    def test_both_names_are_official(self):
        for jp, en in WANT.items():
            rows = _rows(jp)
            self.assertTrue(rows, f"{jp} の行が無い")
            for pid, name_en, sp in rows:
                cn = json.loads(sp or "{}").get("character_name")
                self.assertEqual(name_en, en, f"{pid}: name_en")
                self.assertEqual(cn, en, f"{pid}: character_name (eBay C:Character の元)")

    def test_translated_forms_are_gone(self):
        db = sqlite3.connect(str(api._DB_PATH))
        try:
            for bad in FORBIDDEN:
                n = db.execute(
                    "SELECT COUNT(*) FROM products WHERE category='pokemon_tcg' "
                    "AND (name_en=? OR json_extract(specs,'$.character_name')=?)",
                    (bad, bad)).fetchone()[0]
                self.assertEqual(n, 0, f"{bad!r} が {n} 行残っている")
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
