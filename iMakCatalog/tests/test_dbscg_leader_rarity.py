"""DBSCG Leader の C:Rarity='Leader' 出力 回帰テスト (2026-07-21 HQ 裁定).

依頼: requests/2026-07-21_dbscg_leader_rarity_keep_response.md
- eBay Rarity facet(cat 183454)は FREE_TEXT で正規57値に Leader 相当が無い
  → 'Leader' 出力が正 (空にすると fail-closed skip で Leader カード誤除外)。
- yaml `dragonball.yaml` の旧 `L→\"\"` は是正済 (L→Leader)。
- L★ (parallel) は **2026-08-13 に SCR → Leader へ再是正**。公式 (dbs-cardgame.com/fw) の
  rarity 語彙は L/C/UC/R/SR/SCR/PR の 7 値のみで ★ は rarity ではない (刷り違いマーカー)。
  ★ の意味は Features='Alternative Art' が担う。
  詳細 requests/2026-08-13_dbscg_rarity_ebay_raw_values_response.md
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO.parent))
sys.path.insert(0, str(_REPO))
sys.path.insert(0, str(_REPO / "integrations"))

from iMakCatalog.ebay_filter_map import loader  # noqa: E402
import psa_to_csv as pc  # type: ignore  # noqa: E402


class TestLeaderRarityYaml(unittest.TestCase):
    def test_yaml_L_maps_to_Leader_not_empty(self):
        data = loader.load_yaml(loader.YAML_DIR / "dragonball.yaml")
        m = {e["source"]: e["ebay"] for e in data["rarity"]}
        self.assertEqual(m["L"], "Leader")   # 旧 L→"" は Leader skip を生むため是正済
        # ★ は公式 rarity ではない → yaml に ★ エントリを持たない (2026-08-13)
        self.assertNotIn("L★", m)
        self.assertNotIn("L★★", m)
        # 短縮コードのままだった値も eBay master 実在値へ (2026-08-13)
        self.assertEqual(m["C"], "Common")
        self.assertEqual(m["SCR"], "Secret Rare")


class TestLeaderCardsNotSkipped(unittest.TestCase):
    def test_leader_cards_emit_nonempty_rarity(self):
        """受け入れ条件: FB06-001 / FB01-001 が C:Rarity='Leader'(非空) で skip されない."""
        for num, subj in [("FB06-001", "Android 18"), ("FB01-001", "")]:
            r = pc.lookup_dragonball("DBSCG", num, subj, verbose=False)
            self.assertIsNotNone(r, num)
            self.assertEqual(r.get("rarity_ebay"), "Leader", num)


if __name__ == "__main__":
    unittest.main()
