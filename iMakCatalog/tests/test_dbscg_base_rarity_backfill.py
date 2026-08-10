"""DBSCG 新セット未マージ base の rarity backfill 回帰テスト (2026-07-21).

依頼: requests/2026-07-20_pdca_catalog_queue_tcg.md の DBSCG C:Rarity 空 triage 派生。
真因: FB06/FB07/E/FP/SB01 等の新セットで base(dbfw_official) が rarity 空のまま、rarity を持つ
bandai 行が `_dummy_s1` に取り残されマージされず → C:Rarity 空 → fail-closed skip。
scripts/backfill_dbscg_base_rarity_20260721.py で同名ガード付きで base に backfill 済。
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
import psa_to_csv as pc  # type: ignore  # noqa: E402

CAT = "dragonball_scg"


class TestDbscgBaseRarityBackfill(unittest.TestCase):
    def test_battle_base_now_has_rarity(self):
        """FB06-002 (BATTLE, 旧 dbfw null) は bandai 兄弟 SR で埋まり非空を出力."""
        r = pc.lookup_dragonball("DBSCG FB06", "FB06-002", "Fusion Android 13")
        self.assertIsNotNone(r)
        self.assertEqual(r.get("rarity_ebay"), "Super Rare")

    def test_backfilled_row_provenance(self):
        rec = api.lookup(category=CAT, product_id="FB06-002")
        self.assertEqual(rec["specs"].get("rarity"), "SR")
        self.assertIn("backfill", rec["specs"].get("spec_source", ""))

    def test_number_divergence_not_backfilled(self):
        """FB07-025 base=Omega Shenron に _dummy_s1=Syn Shenron の rarity を注入しない
        (同番だが別カード=番号分裂。名前ガードで弾く).

        ★2026-08-10 更新: FB07-025 は LEADER のため 2026-08-10 leader backfill (rule=LEADER→'L')
        で spec_source が入る。ここでのテスト意図は
        「7/21 の name-guard sibling-backfill (spec_source='..._nameguard_...') が発火していないこと」。
        LEADER 直接派生 (spec_source='dbscg_leader_rarity_backfill_20260810') は許容。
        """
        rec = api.lookup(category=CAT, product_id="FB07-025")
        self.assertIsNotNone(rec)
        spec_source = (rec["specs"].get("spec_source") or "")
        # name-guard sibling-backfill が発火していないこと (名前分裂は今も安全)
        self.assertNotIn("nameguard", spec_source)
        self.assertNotIn("dbscg_base_rarity_backfill_20260721", spec_source)
        self.assertNotIn("dbscg_variant_rarity_nameguard_backfill_20260728", spec_source)

    def test_no_sibling_stays_empty_failclosed(self):
        """rarity を持つ bandai 兄弟が無い base は空のまま (fail-closed)."""
        r = pc.lookup_dragonball("DBSCG FB07", "FB07-033", "")
        # 空 or None を許容 (推測で埋めない)
        self.assertIn((r or {}).get("rarity_ebay", ""), ("", None))


if __name__ == "__main__":
    unittest.main()
