"""One Piece 新スターターデッキ ST31-36 (2026-07-11 発売) resolve 回帰 (2026-07-24 自走取込).

set_code ST31-36 の eBay set マッピング(=目玉キャラ名, REVIEW値) 追加 + bandai --update 取込 +
raw specs 正規化(opcg_field_normalize + phase_b rarity)まで通した状態を固定する。
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
from iMakCatalog.ebay_filter_map import loader  # noqa: E402

_EXPECT = {
    "ST-31": "Monkey D Luffy", "ST-32": "Roronoa Zoro", "ST-33": "Kuzan",
    "ST-34": "Charlotte Katakuri", "ST-35": "Sabo", "ST-36": "Eustass Kid",
}


class TestST31to36Yaml(unittest.TestCase):
    def test_set_code_mappings(self):
        data = loader.load_yaml(loader.YAML_DIR / "one_piece.yaml")
        m = {e["source"]: e["ebay"] for e in data["set_code"]}
        for code, ebay in _EXPECT.items():
            self.assertEqual(m.get(code), ebay, code)


class TestST31to36Resolve(unittest.TestCase):
    def test_listable_name_rarity_set(self):
        """C:Rarity/C:Set が非空で listing 可能なこと (rarity 正規化まで通過)."""
        cases = [
            ("ONE PIECE JAPANESE ST31-STARTER DECK", "001", "SANJI", "Monkey D Luffy"),
            ("ONE PIECE JAPANESE ST34-STARTER DECK", "001", "CHARLOTTE KATAKURI", "Charlotte Katakuri"),
        ]
        for brand, num, subj, set_ebay in cases:
            r = pc.lookup_one_piece(brand, num, subj, verbose=False)
            self.assertIsNotNone(r, brand)
            self.assertTrue(r.get("name_en") or r.get("card_name"), brand)
            self.assertTrue(r.get("rarity"), f"{brand} rarity empty")
            self.assertEqual(r.get("set_name_ebay"), set_ebay, brand)


if __name__ == "__main__":
    unittest.main()
