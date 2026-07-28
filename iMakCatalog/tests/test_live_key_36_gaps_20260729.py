"""2026-07-29 live cert 残 36件 gap 対応の回帰テスト.

- character_name backfill (DBSCG _p1 は base から / OP P- は name_en から)
- OP promo/event set_name_ebay yaml マッピング
"""
from __future__ import annotations
import sys
from pathlib import Path
_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO.parent)); sys.path.insert(0, str(_REPO)); sys.path.insert(0, str(_REPO / "integrations"))
import unittest
from iMakCatalog import api


class TestCharacterNameBackfill(unittest.TestCase):
    def test_dbscg_p1_character_from_base(self):
        for pid, ch in [("FB01-140_p1", "Son Gohan : Childhood"),
                        ("SB02-058_p1", "King Piccolo"), ("SB02-060_p1", "Red Ribbon Robot")]:
            rec = api.lookup(category="dragonball_scg", product_id=pid)
            self.assertEqual(rec["specs"].get("character_name"), ch, pid)

    def test_op_promo_character_from_nameen(self):
        for pid, ch in [("P-033", "Monkey D. Luffy"), ("P-066", "Boa Hancock"),
                        ("P-110", "Monkey D. Luffy")]:
            rec = api.lookup(category="one_piece_tcg", product_id=pid)
            self.assertEqual(rec["specs"].get("character_name"), ch, pid)


class TestOpPromoSetBackfill(unittest.TestCase):
    def test_op_promo_event_sets_resolve(self):
        expect = {
            "OP01-001_p1": "Promo Cards", "OP01-017_p2": "Promo Cards",
            "OP03-044_p2": "Promo Cards", "OP12-031_p2": "Promo Cards",
            "ST01-006_p1": "Promo Cards", "ST01-013_p3": "Promo Cards",
            "OP06-118_p4": "500 Years in the Future",
        }
        for pid, ebay in expect.items():
            rec = api.lookup(category="one_piece_tcg", product_id=pid)
            self.assertEqual(rec["set_name"], ebay, pid)


if __name__ == "__main__":
    unittest.main()
