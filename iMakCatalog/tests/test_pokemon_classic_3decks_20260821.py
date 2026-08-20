"""ポケモンカードゲーム クラシック 3デッキ (CLF/CLK/CLL) の解決 (2026-08-21).

Classic は PSA 依頼が来るたびに1枚ずつ足していた (CLK-008 7/18 / CLF-001 8/15 /
CLL-002 8/20 で3回目)。96枚を一括投入し、set_code 抽出も3デッキぶん通した。
「また1枚ずつ足す」に戻らないよう、3デッキとも解決することを固定する。
"""
from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))

import api  # noqa: E402
from integrations.psa_to_csv import lookup_pokemon  # noqa: E402

BRAND = {
    "CLF": "POKEMON JAPANESE CLF-TRADING CARD GAME CLASSIC VENUSAUR & LUGIA EX DECK",
    "CLK": "POKEMON JAPANESE CLK-TRADING CARD GAME CLASSIC BLASTOISE & SUICUNE EX DECK",
    "CLL": "POKEMON JAPANESE CLL-TRADING CARD GAME CLASSIC CHARIZARD & HO-OH EX DECK",
}


def cid(brand: str, num: str, subject: str):
    r = lookup_pokemon(brand, num, subject, verbose=False)
    if not r:
        return None
    return r.get("card_id") or r.get("product_id")


class TestClassicDecksComplete(unittest.TestCase):
    def test_all_three_decks_have_32_cards(self):
        db = sqlite3.connect(api._DB_PATH)
        for code in ("CLF", "CLK", "CLL"):
            n = db.execute(
                "SELECT COUNT(*) FROM products WHERE category='pokemon_tcg' "
                "AND product_id LIKE ?", (f"{code}-%",)).fetchone()[0]
            self.assertEqual(n, 32, f"{code} が 32枚でない ({n})")
        db.close()

    def test_rarity_is_blank_by_design(self):
        """Classic は printed rarity 記号を持たない → 空が正 (推測で埋めない)."""
        db = sqlite3.connect(api._DB_PATH)
        rows = db.execute(
            "SELECT product_id, json_extract(specs,'$.rarity') FROM products "
            "WHERE category='pokemon_tcg' AND product_id LIKE 'CL%'").fetchall()
        db.close()
        self.assertTrue(rows)
        for pid, rar in rows:
            self.assertIn(rar, ("", None), f"{pid} に rarity が入っている: {rar!r}")


class TestClassicResolves(unittest.TestCase):
    def test_cll_002_charmeleon(self):
        """8/20 の依頼そのもの (cert156684617)."""
        self.assertEqual(cid(BRAND["CLL"], "002", "CHARMELEON"), "CLL-002")

    def test_clk_008_lapras_still_works(self):
        self.assertEqual(cid(BRAND["CLK"], "008", "LAPRAS"), "CLK-008")

    def test_clf_001_bulbasaur_still_works(self):
        self.assertEqual(cid(BRAND["CLF"], "001", "BULBASAUR"), "CLF-001")

    def test_ex_card_resolves(self):
        """チェイスカード (ホウオウex) が引けること."""
        self.assertEqual(cid(BRAND["CLL"], "007", "HO-OH EX"), "CLL-007")

    def test_decks_do_not_cross_resolve(self):
        """デッキ名が違えば別 set_code になる (同じ番号でも混ざらない)."""
        self.assertEqual(cid(BRAND["CLF"], "003", "VENUSAUR"), "CLF-003")
        self.assertEqual(cid(BRAND["CLL"], "003", "CHARIZARD"), "CLL-003")
        self.assertEqual(cid(BRAND["CLK"], "003", "BLASTOISE"), "CLK-003")


if __name__ == "__main__":
    unittest.main()
