"""DragonBall Energy Marker resolve test (2026-06-11).

依頼: requests/2026-06-11_psa_preflight_full_audit_indexfail_and_gaps.md (GAP)。
ENERGY MARKER alt-art 系が GAP 誤判定だった真因の再発防止:
  ① card_number が set-prefix 込み (E01-02) → 二重接頭辞 (E01-E01-02) で外す
  ② name_en=None で PSA subject「ENERGY MARKER」が照合できず reject
両方を解消し、alt-art は _p1 variant に解決すること。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))
sys.path.insert(0, str(_REPO / "integrations"))

import psa_to_csv as pc  # type: ignore  # noqa: E402
import api  # type: ignore  # noqa: E402


class TestEnergyMarkerNameEn(unittest.TestCase):
    def test_name_en_populated(self):
        # migration で name_en='Energy Marker' が入っていること
        r = api.lookup("dragonball_scg", "E01-02")
        self.assertIsNotNone(r)
        self.assertEqual(r["name_en"], "Energy Marker")


class TestEnergyMarkerResolve(unittest.TestCase):
    def test_alt_art_resolves_to_p1_variant(self):
        # card_number='E01-02'(set接頭辞込み) + ALTERNATE ART → E01-02_p1 に解決
        r = pc.lookup_dragonball(
            "ENERGY MARKER", "E01-02",
            subject="ENERGY MARKER ALTERNATE ART", verbose=False)
        self.assertIsNotNone(r)
        self.assertEqual(r["card_id"], "E01-02_p1")

    def test_e_series_full_pid_resolves(self):
        # 'E-04' (set_code 誤抽出ケース) も full pid として解決
        r = pc.lookup_dragonball(
            "ENERGY MARKER", "E-04", subject="ENERGY MARKER", verbose=False)
        self.assertIsNotNone(r)
        self.assertEqual(r["card_id"], "E-04")

    def test_nonexistent_number_fail_closed(self):
        r = pc.lookup_dragonball(
            "ENERGY MARKER", "E01-99", subject="ENERGY MARKER", verbose=False)
        self.assertIsNone(r)

    def test_name_mismatch_rejected(self):
        # 別キャラ subject で E01-02 を引いても name 照合で reject (誤マッチ防止)
        r = pc.lookup_dragonball(
            "ENERGY MARKER", "E01-02", subject="SON GOKU", verbose=False)
        self.assertIsNone(r)


if __name__ == "__main__":
    unittest.main()
