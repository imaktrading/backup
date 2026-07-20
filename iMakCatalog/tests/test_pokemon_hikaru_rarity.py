"""ひかるポケモン rarity 欠落の再発防止 test (2026-07-20).

依頼: requests/2026-07-20_pdca_catalog_queue_tcg.md 層A
      (m68129506725 Shining Celebi = 必須 Item Specific 'C:Rarity' 空)。

真因: scrapers/pokemon_tcg.py の rarity 抽出が `rarity/ic_rare_*.gif` だけを見ており、
公式が別命名で出す `ic_hikaru.gif` (ひかるポケモン) を取りこぼしていた。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO.parent))
sys.path.insert(0, str(_REPO))
sys.path.insert(0, str(_REPO / "integrations"))

from iMakCatalog import api  # noqa: E402
from iMakCatalog.scrapers import pokemon_tcg as pk  # noqa: E402

_HIKARU = ["SM3p-004", "SM3p-010", "SM3p-028", "SM3p-041",
           "SM3p-043", "SM3p-057", "SM3p-058", "SM3p-059"]


class TestHikaruRarityMap(unittest.TestCase):
    def test_alt_rarity_image_maps_to_H(self):
        self.assertEqual(pk._RARITY_IMG_ALT["hikaru"], "H")


class TestHikaruCatalogRows(unittest.TestCase):
    def test_all_shining_pokemon_have_ebay_rarity(self):
        """C:Rarity は rarity_ebay から出るので、ここが空だと出品側で必須欠落になる."""
        for pid in _HIKARU:
            rec = api.lookup(category="pokemon_tcg", product_id=pid)
            self.assertIsNotNone(rec, pid)
            specs = rec["specs"]
            self.assertEqual(specs.get("rarity"), "H", pid)
            # eBay 公式 facet は 'Shiny Holo Rare' (× 'Shining Holo Rare')
            self.assertEqual(specs.get("rarity_ebay"), "Shiny Holo Rare", pid)


if __name__ == "__main__":
    unittest.main()
