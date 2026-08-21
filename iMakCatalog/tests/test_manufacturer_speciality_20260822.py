"""Manufacturer / Speciality の埋め方 (2026-08-22).

eBay の aspect 全35項目を並べた結果、RECOMMENDED なのに 0% だった項目のうち
**根拠を持って埋められる2つ** を入れた。

守る不変条件:
  A) Manufacturer は category から一意 / eBay の一覧に在る綴り
  B) Speciality は **カード名の末尾一致** のみ (途中の 'ex' に誤爆しない)
  C) VSTAR は eBay の Speciality に無いので空欄のまま (V に寄せない)
  D) ポケモン以外に Speciality を入れない
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO.parent))
sys.path.insert(0, str(_REPO))
import api  # noqa: E402

MASTER = Path(r"C:\dev\iMak_data\catalog\_input\ebay_aspects_183454_latest.json")


def _ebay(aspect):
    return set(json.loads(MASTER.read_text(encoding="utf-8"))["aspects"][aspect]["all"])


class TestManufacturer(unittest.TestCase):
    def test_values_exist_on_ebay(self):
        ok = _ebay("Manufacturer")
        for cat in ("pokemon_tcg", "one_piece_tcg", "dragonball_scg",
                    "gundam_tcg", "yugioh_tcg"):
            v = api.derive_manufacturer(cat)
            self.assertIsNotNone(v, f"{cat} の Manufacturer が None")
            self.assertIn(v, ok, f"{v!r} が eBay の一覧に無い")

    def test_unknown_category_is_none(self):
        self.assertIsNone(api.derive_manufacturer("montbell"))


class TestSpeciality(unittest.TestCase):
    def test_suffix_only(self):
        """名前の途中に 'ex' があっても拾わない."""
        self.assertEqual(api.derive_speciality("pokemon_tcg", "Lugia ex"), "EX")
        self.assertIsNone(api.derive_speciality("pokemon_tcg", "Ex Machina"))

    def test_vstar_stays_blank(self):
        """VSTAR は eBay の Speciality に無い。V に寄せない."""
        self.assertIsNone(api.derive_speciality("pokemon_tcg", "Charizard VSTAR"))

    def test_only_pokemon(self):
        self.assertIsNone(api.derive_speciality("one_piece_tcg", "Monkey D. Luffy V"))

    def test_values_exist_on_ebay(self):
        ok = _ebay("Speciality")
        for name in ("Charizard VMAX", "Pikachu V", "Mewtwo-GX",
                     "Lugia ex", "Rayquaza BREAK"):
            v = api.derive_speciality("pokemon_tcg", name)
            self.assertIn(v, ok, f"{name!r} -> {v!r} が eBay の一覧に無い")


if __name__ == "__main__":
    unittest.main()
