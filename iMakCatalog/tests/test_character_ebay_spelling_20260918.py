# -*- coding: utf-8 -*-
"""C:Character を eBay の綴りに寄せる判定の回帰テスト (2026-09-18).

守りたいこと:
- ♀♂ が入れ替わらない (正規化すると同じキーに落ちるため、記号で行き先を決めている)
- 一覧に無い名前は**触らない** (新しい種・ワンピース等は天井。空欄化もしない)
- 形を外した名前が一覧に無い時は触らない (fail-closed)
- 遊戯王は対象外 (出品していない)
"""
from __future__ import annotations

import importlib.util
import json
import sqlite3
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MIG = ROOT / "migrations" / "2026-09-18_pokemon_character_ebay_spelling.py"

_spec = importlib.util.spec_from_file_location("_char_rules", MIG)
rules = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rules)

ALLOWED = {"Ho-Oh", "Unown", "Nidoran (♀)", "Nidoran (♂)", "Mewtwo", "Pikachu", "Charizard"}


def make_db(rows):
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE products (id INTEGER PRIMARY KEY, category TEXT, specs TEXT, updated_at TEXT)")
    for i, (cat, ch) in enumerate(rows, 1):
        db.execute("INSERT INTO products (id, category, specs) VALUES (?,?,?)",
                   (i, cat, json.dumps({"character_name": ch}, ensure_ascii=False)))
    return db


def plan_map(rows):
    db = make_db(rows)
    return {old: (new, form) for _, _, old, new, form, _ in rules.plan(db, ALLOWED)}


class CharacterSpellingRules(unittest.TestCase):
    def test_spelling_variants(self):
        got = plan_map([("pokemon_tcg", "Ho-oh"), ("pokemon_tcg", "Unown [?]")])
        self.assertEqual(got["Ho-oh"], ("Ho-Oh", None))
        self.assertEqual(got["Unown [?]"], ("Unown", None))

    def test_nidoran_gender_not_swapped(self):
        got = plan_map([("pokemon_tcg", "Nidoran♀"), ("pokemon_tcg", "Nidoran♂")])
        self.assertEqual(got["Nidoran♀"][0], "Nidoran (♀)")
        self.assertEqual(got["Nidoran♂"][0], "Nidoran (♂)")

    def test_form_moves_to_speciality(self):
        got = plan_map([("pokemon_tcg", "Mewtwo-EX"), ("pokemon_tcg", "Pikachu ex"),
                        ("pokemon_tcg", "Charizard VMAX")])
        self.assertEqual(got["Mewtwo-EX"], ("Mewtwo", "EX"))
        self.assertEqual(got["Pikachu ex"], ("Pikachu", "EX"))
        self.assertEqual(got["Charizard VMAX"], ("Charizard", "VMAX"))

    def test_not_in_list_is_left_alone(self):
        """一覧に無い = 誤りではない。空欄にもしない (天井)."""
        got = plan_map([("pokemon_tcg", "Morpeko"), ("one_piece_tcg", "Monkey D. Luffy"),
                        ("pokemon_tcg", "Morpeko V")])  # 形を外しても一覧に無い
        self.assertEqual(got, {})

    def test_non_character_values_blanked(self):
        got = plan_map([("one_piece_tcg", "DON!! Card"), ("dragonball_scg", "Energy Marker"),
                        ("pokemon_tcg", "Basic Water Energy")])
        self.assertEqual({k: v[0] for k, v in got.items()},
                         {"DON!! Card": None, "Energy Marker": None, "Basic Water Energy": None})

    def test_yugioh_excluded(self):
        self.assertEqual(plan_map([("yugioh_tcg", "Ho-oh"), ("yugioh_tcg", "DON!! Card")]), {})

    def test_already_correct_is_untouched(self):
        self.assertEqual(plan_map([("pokemon_tcg", "Pikachu"), ("pokemon_tcg", "Nidoran (♀)")]), {})


if __name__ == "__main__":
    unittest.main()
