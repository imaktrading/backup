"""Pokemon MEGA拡張「アビスアイ」[M5] resolve 回帰テスト (2026-07-24).

自走発見: M5 メインセット81種は収録済だったが set_name/set_name_ebay 欠落 + brand→code
未登録で resolve 不能 (M1-M4 は整備済)。eBay facet = "Abyss Eye"。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO.parent))
sys.path.insert(0, str(_REPO))
sys.path.insert(0, str(_REPO / "integrations"))

import psa_to_csv as pc  # type: ignore  # noqa: E402
from iMakCatalog import api  # noqa: E402


class TestM5AbyssEye(unittest.TestCase):
    def test_brand_keyword_maps_to_M5(self):
        self.assertEqual(
            pc.extract_set_code_from_brand_pokemon("POKEMON JAPANESE ABYSS EYE"), "M5")

    def test_m5_resolves_with_abyss_eye_set(self):
        r = pc.lookup_pokemon("POKEMON JAPANESE ABYSS EYE", "001", "TROPIUS")
        self.assertIsNotNone(r)
        self.assertEqual(r.get("card_id"), "M5-001")
        self.assertEqual(r.get("set_name_ebay"), "Abyss Eye")

    def test_m5_records_have_set_name(self):
        rec = api.lookup(category="pokemon_tcg", product_id="M5-040")
        self.assertIsNotNone(rec)
        self.assertTrue(rec["specs"].get("set_name_ebay"))  # 非空 (旧: 空で skip)


if __name__ == "__main__":
    unittest.main()
