"""promo fallback: CSV 出力等価な同点は決定的採用 / 差あれば reject 維持 (2026-08-01 窓口GO)."""
from __future__ import annotations
import sys
from pathlib import Path
_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO.parent)); sys.path.insert(0, str(_REPO)); sys.path.insert(0, str(_REPO / "integrations"))
import unittest
import psa_to_csv as pc  # type: ignore

_BR = "ONE PIECE JAPANESE LET'S START CAMPAIGN PROMOTION PACK"


class TestPromoTieEquivalence(unittest.TestCase):
    def test_a_perona_equivalent_tie_deterministic(self):
        """(a) 等価同点 → 決定的採用 (min pid = _p4)."""
        r = pc.lookup_one_piece(_BR, "077", "PERONA", verbose=False)
        self.assertEqual((r or {}).get("card_id"), "OP01-077_p4")

    def test_d_all_7_lets_start_resolve(self):
        """(d) 始めようキャンペーン系統 7カード 全部が決定的解決 (min pid)."""
        expect = {
            "077": "OP01-077_p4", "006": "EB01-006_p4", "046": "EB01-046_p2",
            "021": "OP07-021_p2", "074": "OP08-074_p2", "050": "OP09-050_p2",
            "106": "OP09-106_p1",
        }
        subj = {"077": "PERONA", "006": "TONY TONY CHOPPER", "046": "BROOK",
                "021": "UROUGE", "074": "BLACK MARIA", "050": "NAMI", "106": "NICO OLVIA"}
        for num, pid in expect.items():
            r = pc.lookup_one_piece(_BR, num, subj[num], verbose=False)
            self.assertEqual((r or {}).get("card_id"), pid, num)

    def test_b_different_csv_values_not_merged(self):
        """(b) CSV 値が1つでも違えば署名が異なる = 同点でも採用されず reject 維持."""
        base = {"name_en": "X", "name": "X",
                "specs": {"set_name_ebay": "Promo Cards", "rarity_ebay": "Uncommon",
                          "character_name": "X", "finish": "", "features": ["Promo"],
                          "card_type_ebay": "Character"}}
        same = {**base, "product_id": "A_p2", "specs": dict(base["specs"])}
        diff = {**base, "product_id": "A_p3",
                "specs": {**base["specs"], "rarity_ebay": "Super Rare"}}  # rarity だけ違う
        self.assertEqual(pc._promo_csv_output_sig(same), pc._promo_csv_output_sig(base))
        self.assertNotEqual(pc._promo_csv_output_sig(diff), pc._promo_csv_output_sig(base))

    def test_c_forced_key_not_overridden_by_resolver(self):
        """(c) resolver は決定的・内容ベースで、HQ の forced_card_id を知らない (上書きしない)。
        catalog resolver に forced 概念は無く、HQ pipeline が手動KEYを resolver 出力より先に適用する。
        ここでは resolver が **同じ入力に同じ product_id** を返す決定性のみ検証 (非上書きの前提)."""
        a = pc.lookup_one_piece(_BR, "077", "PERONA", verbose=False)
        b = pc.lookup_one_piece(_BR, "077", "PERONA", verbose=False)
        self.assertEqual((a or {}).get("card_id"), (b or {}).get("card_id"))

    def test_regression_edition_hit_unchanged(self):
        r = pc.lookup_one_piece(
            "ONE PIECE JAPANESE PREMIUM CARD COLLECTION -BEST SELECTION VOL.4-",
            "049", "SABO", verbose=False)
        self.assertEqual((r or {}).get("card_id"), "OP10-049_p1")


if __name__ == "__main__":
    unittest.main()
