"""base→_pN name-guard 回帰テスト (2026-08-01, 窓口指定3本).

依頼: requests/2026-08-01_hq_decisions_nameguard_facet_fb10049.md ①。
1. name_jp 不一致の _p1 に伝播しないこと (fail-closed)
2. name_jp 一致の _p1 には伝播すること (全部止めていないことの確認)
3. FB10-025_p1 / FB10-049_p1 を再伝播しても base の誤値が再発しないこと (retrospective)
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO.parent))
sys.path.insert(0, str(_REPO))

from iMakCatalog.name_guard import propagate_name_fields, base_product_id


class TestGuardRejectsMismatch(unittest.TestCase):
    def test1_name_jp_mismatch_no_propagate(self):
        """FB10-025_p1 (ベジット) vs base (孫悟空/ベジータ) → 伝播しない."""
        r = propagate_name_fields(
            variant_name_jp="ベジット", base_name_jp="孫悟空/ベジータ",
            base_name_en="Son Goku/Vegeta", base_character_name="Son Goku/Vegeta")
        self.assertEqual(r, {})

    def test1b_partial_match_no_propagate(self):
        """幼年期 vs 青年期 の部分一致も通さない (FB10-049_p1)."""
        r = propagate_name_fields(
            variant_name_jp="孫悟飯：青年期/ピッコロ",
            base_name_jp="孫悟飯：幼年期/ピッコロ",
            base_name_en="Son Gohan : Youth/Piccolo",
            base_character_name="Son Gohan : Youth/Piccolo")
        self.assertEqual(r, {})


class TestGuardAllowsMatch(unittest.TestCase):
    def test2_name_jp_exact_match_propagates_both(self):
        """name_jp 完全一致なら name_en/character_name 両方伝播 (全部は止めていない)."""
        r = propagate_name_fields(
            variant_name_jp="ロロノア・ゾロ", base_name_jp="ロロノア・ゾロ",
            base_name_en="Roronoa Zoro", base_character_name="Roronoa Zoro")
        self.assertEqual(r, {"name_en": "Roronoa Zoro", "character_name": "Roronoa Zoro"})


class TestRetrospectiveNoReintroduction(unittest.TestCase):
    def test3_fb10_025_and_049_not_reintroduced(self):
        """base の誤値 (Son Goku/Vegeta 等) を再伝播しない = 再発しない."""
        # FB10-025_p1: 再実行しても base 'Son Goku/Vegeta' を焼かない
        self.assertEqual(
            propagate_name_fields("ベジット", "孫悟空/ベジータ",
                                  "Son Goku/Vegeta", "Son Goku/Vegeta"), {})
        # FB10-049_p1: base 幼年期 の英名を焼かない
        self.assertEqual(
            propagate_name_fields("孫悟飯：青年期/ピッコロ", "孫悟飯：幼年期/ピッコロ",
                                  "Son Gohan : Youth/Piccolo",
                                  "Son Gohan : Youth/Piccolo"), {})

    def test3b_base_id_strip(self):
        self.assertEqual(base_product_id("FB10-025_p1"), "FB10-025")
        self.assertEqual(base_product_id("FB10-049_p3"), "FB10-049")


if __name__ == "__main__":
    unittest.main()
