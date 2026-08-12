"""adapter set_name_ebay 優先順位 反転 (2026-08-12 Advisor GO) の回帰テスト.

依頼: iMak_data/catalog/requests/2026-08-11_pdca_catalog_queue_tcg_response_question_response.md
  §決定 案A commit 2 — `_apply_ebay_fields` の OPCG/Gundam/DBSCG 分岐を反転:
    (旧) record.set_name or specs.set_name_ebay or ""
    (新) specs.set_name_ebay or record.set_name or ""
  SSOT 契約 §1-1 = specs.set_name_ebay が権威.

このテストが守る不変条件:
  A) adapter 出力の優先順位が specs 優先 (unit テスト、DB 非依存).
  B) 実 DB を通した canonical row (OP06-022 / GD01-100_GD03_SP / SB02-001_p1 等) で
     反転前後の期待値と同じ値が得られる.
  C) E01-* 24 行の adapter 出力が英語 canonical 'Energy Marker Pack 01' である
     (反転で bug fix. 反転前は Katakana 長形が出ていた).
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO.parent))
sys.path.insert(0, str(_REPO))
import api  # type: ignore  # noqa: E402
from integrations import psa_to_csv as catalog_psa  # type: ignore  # noqa: E402


class TestAdapterPreferSpecs(unittest.TestCase):
    """A: unit テスト. OPCG/Gundam/DBSCG は specs 優先 fallback record.set_name."""

    CATS = ("one_piece_tcg", "gundam_tcg", "dragonball_scg")

    def test_specs_wins_when_both_populated(self):
        for cat in self.CATS:
            record = {"specs": {"set_name_ebay": "SPECS_VALUE"},
                      "set_name": "RECORD_VALUE"}
            legacy = {}
            catalog_psa._apply_ebay_fields(legacy, record, cat)
            self.assertEqual(
                legacy["set_name_ebay"], "SPECS_VALUE",
                f"{cat}: specs 優先されていない: {legacy['set_name_ebay']!r}")

    def test_falls_back_to_record_when_specs_empty(self):
        for cat in self.CATS:
            record = {"specs": {"set_name_ebay": ""},
                      "set_name": "RECORD_VALUE"}
            legacy = {}
            catalog_psa._apply_ebay_fields(legacy, record, cat)
            self.assertEqual(
                legacy["set_name_ebay"], "RECORD_VALUE",
                f"{cat}: record fallback していない: {legacy['set_name_ebay']!r}")

    def test_empty_when_both_empty(self):
        for cat in self.CATS:
            record = {"specs": {"set_name_ebay": None}, "set_name": None}
            legacy = {}
            catalog_psa._apply_ebay_fields(legacy, record, cat)
            self.assertEqual(legacy["set_name_ebay"], "")


class TestReversalPreservesCanonicalOutput(unittest.TestCase):
    """B: 実 DB canonical row で adapter 出力が期待値."""

    def _apply(self, cat, pid):
        rec = api.lookup(category=cat, product_id=pid)
        assert rec is not None, f"{pid} が DB に無い"
        legacy = {}
        catalog_psa._apply_ebay_fields(legacy, rec, cat)
        return legacy["set_name_ebay"]

    def test_op06_022_wings_of_the_captain(self):
        self.assertEqual(
            self._apply("one_piece_tcg", "OP06-022"),
            "Wings of the Captain")

    def test_st16_005_green_uta_prefix(self):
        """ST-16 (2026-08-02 GREEN prefix 追加). 反転前は 'Uta'/反転後は 'GREEN Uta'
        が返るはず (specs = 'GREEN Uta' に populate 済)."""
        self.assertEqual(
            self._apply("one_piece_tcg", "ST16-005"), "GREEN Uta")

    def test_prb02_005_premium_booster_vol2(self):
        self.assertEqual(
            self._apply("one_piece_tcg", "PRB02-005"),
            "Premium Booster Vol.2")

    def test_gundam_gd01_100_gd03_sp_steel_requiem(self):
        """gundam 'Universal Strife'→'Steel Requiem' 反映."""
        self.assertEqual(
            self._apply("gundam_tcg", "GD01-100_GD03_SP"),
            "Steel Requiem")

    def test_dbscg_sb02_001_p1_manga_booster(self):
        """DBSCG 'Critical Blow'→'Manga Booster 02' 反映."""
        self.assertEqual(
            self._apply("dragonball_scg", "SB02-001_p1"),
            "Manga Booster 02")


class TestE01BugFixOutput(unittest.TestCase):
    """C: E01-* 24 行の adapter 出力が英語 canonical (反転で bug fix)."""

    def test_e01_01_energy_marker_pack_english(self):
        rec = api.lookup(category="dragonball_scg", product_id="E01-01")
        self.assertIsNotNone(rec, "E01-01 が DB に無い")
        legacy = {}
        catalog_psa._apply_ebay_fields(legacy, rec, "dragonball_scg")
        self.assertEqual(
            legacy["set_name_ebay"], "Energy Marker Pack 01",
            "E01-01 の adapter 出力が英語 canonical でない "
            f"(反転前の Katakana 長形が出ている疑い): {legacy['set_name_ebay']!r}")


class TestPokemonUnaffected(unittest.TestCase):
    """Pokemon 分岐は既に specs 優先で不変 (反転対象外)."""

    def test_pokemon_still_specs_only(self):
        record = {"specs": {"set_name_ebay": "SPECS_VALUE"}, "set_name": "IGNORED"}
        legacy = {}
        catalog_psa._apply_ebay_fields(legacy, record, "pokemon_tcg")
        # Pokemon は fallback 無し = specs のみ
        self.assertEqual(legacy["set_name_ebay"], "SPECS_VALUE")

    def test_pokemon_empty_specs_stays_empty(self):
        record = {"specs": {"set_name_ebay": ""}, "set_name": "RECORD_VALUE"}
        legacy = {}
        catalog_psa._apply_ebay_fields(legacy, record, "pokemon_tcg")
        # Pokemon は record fallback しない (JP set_name 混入回避)
        self.assertEqual(legacy["set_name_ebay"], "")


if __name__ == "__main__":
    unittest.main()
