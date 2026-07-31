"""Ultra Prism 誤マップ 327件 空欄化 + ベジット FB10-025_p1 修正 の回帰 (2026-08-01)."""
from __future__ import annotations
import sys
from pathlib import Path
_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO.parent)); sys.path.insert(0, str(_REPO)); sys.path.insert(0, str(_REPO / "integrations"))
import unittest, sqlite3, json
import psa_to_csv as pc  # type: ignore
from iMakCatalog import api

DB = "C:/dev/iMak_data/catalog/products.sqlite"


class TestUltraPrismReverted(unittest.TestCase):
    def test_no_row_maps_to_ultra_prism(self):
        c = sqlite3.connect(DB)
        n = c.execute("select count(*) from products where category='pokemon_tcg' "
                      "and json_extract(specs,'$.set_name_ebay')='Sun & Moon—Ultra Prism'").fetchone()[0]
        self.assertEqual(n, 0)

    def test_resolver_csset_empty_for_blanked(self):
        r = pc.lookup_pokemon("POKEMON JAPANESE ULTRA SUN", "001", "", verbose=False)
        self.assertEqual((r or {}).get("set_name_ebay"), "")


class TestVegitoFix(unittest.TestCase):
    def test_fb10_025_p1_vegito(self):
        rec = api.lookup(category="dragonball_scg", product_id="FB10-025_p1")
        self.assertEqual(rec.get("name_en"), "Vegito")
        self.assertEqual(rec["specs"].get("character_name"), "Vegito")
        self.assertEqual(rec.get("name_jp"), "ベジット")  # JP は不変


if __name__ == "__main__":
    unittest.main()
