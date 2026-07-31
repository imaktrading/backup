"""2026-07-28 自走/HQ verdict 対応の回帰テスト.

1) OP Perona "LET'S START CAMPAIGN" (始めようキャンペーン) → p4/p5 へ steer (fail-closed tie)。
   HQ verdict 2026-07-27: cert153420191 = OP01-077_p5。★の p4/p5 判別は画像のみ可のため
   同点 reject で HQ viewer が確定。resolver は汎用_P でなく始めようキャンペーン系を最上位にする。
2) Pokemon MC (スタートデッキ100 バトルコレクション) set backfill: set 非空 + rarity 空(deck=正)。
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


class TestLetsStartCampaign(unittest.TestCase):
    def test_perona_steers_to_hajimeyou_series(self):
        """汎用_P でなく始めようキャンペーン系(p4/p5)を最上位にする。
        2026-08-01 窓口GO で挙動変更: p4/p5 は ★差のみ=CSV出力等価なので、fail-closed でなく
        決定的採用 (min pid=_p4)。詳細は test_promo_tie_csv_equivalence_20260801。"""
        r = pc.lookup_one_piece(
            "ONE PIECE JAPANESE LET'S START CAMPAIGN PROMOTION PACK", "077", "PERONA",
            verbose=False)
        self.assertEqual((r or {}).get("card_id"), "OP01-077_p4")

    def test_regression_sabo_best_selection(self):
        r = pc.lookup_one_piece(
            "ONE PIECE JAPANESE PREMIUM CARD COLLECTION -BEST SELECTION VOL.4-",
            "049", "SABO", verbose=False)
        self.assertEqual((r or {}).get("card_id"), "OP10-049_p1")

    def test_regression_chopper_25th(self):
        r = pc.lookup_one_piece(
            "ONE PIECE JAPANESE 25TH ANNIVERSARY PREMIUM CARD COLLECTION",
            "006", "TONY TONY CHOPPER", verbose=False)
        self.assertEqual((r or {}).get("card_id"), "ST01-006_p1")


class TestMcStartDeck100(unittest.TestCase):
    def test_mc_set_filled_rarity_empty(self):
        r = pc.lookup_pokemon(
            "POKEMON JAPANESE START DECK 100 BATTLE COLLECTION", "227", "PIKACHU EX")
        self.assertIsNotNone(r)
        self.assertEqual(r.get("card_id"), "MC-227")
        self.assertEqual(r.get("set_name_ebay"), "Start Deck 100 Battle Collection")
        # deck カードは印刷レアリティ無し = C:Rarity 空欄が正
        self.assertFalse(r.get("rarity"))


if __name__ == "__main__":
    unittest.main()


class TestSiStartDeck100(unittest.TestCase):
    def test_si_set_filled_rarity_empty(self):
        r = pc.lookup_pokemon("POKEMON JAPANESE START DECK 100", "001", "VENUSAUR V")
        self.assertIsNotNone(r)
        self.assertEqual(r.get("card_id"), "SI-001")
        self.assertEqual(r.get("set_name_ebay"), "Start Deck 100")
        self.assertFalse(r.get("rarity"))  # deck=印刷レアリティ無し=空欄が正


class TestDbscgVariantRarityBackfill(unittest.TestCase):
    def test_leader_variant_gets_leader(self):
        from iMakCatalog import api
        rec = api.lookup(category="dragonball_scg", product_id="FB06-001_p1")
        self.assertEqual(rec["specs"].get("rarity_ebay"), "Leader")

    def test_battle_variant_gets_rarity(self):
        from iMakCatalog import api
        rec = api.lookup(category="dragonball_scg", product_id="FB06-002_p1")
        self.assertEqual(rec["specs"].get("rarity_ebay"), "Super Rare")

    def test_number_divergence_stays_empty(self):
        """FB07-025 base=Omega Shenron に sibling(Syn Shenron)の rarity を焼かない (name-guard)."""
        from iMakCatalog import api
        for pid in ("FB07-025", "FB07-025_p1"):
            rec = api.lookup(category="dragonball_scg", product_id=pid)
            self.assertFalse(rec["specs"].get("rarity"), pid)
