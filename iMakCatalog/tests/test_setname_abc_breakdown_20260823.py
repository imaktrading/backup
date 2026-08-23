"""restamp の a/b/c 内訳を固定する (2026-08-23).

窓口 requests/2026-08-19_set_name_151_form_response.md の手順1:
  「dry-run で差分一覧を出す (どの値 → どの値に何行、**a/b/c の内訳**)。ここで一度止める」

契約 v1.2 §1-3 の 3 状態:
  (a) canonical … eBay master (Game 別) に在る値
  (b) 自由文字列 … master に無い。公式のセット名をそのまま維持
  (c) 空         … セットが特定できない

★分類を間違えると「master に無い値」を canonical と数えて、
  「全部 master に当たっています」と誤報告することになる。そこを固定する。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))

import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "restamp_set_name_ebay", ROOT / "tools" / "restamp_set_name_ebay.py")
restamp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(restamp)


class TestAbcState(unittest.TestCase):
    def setUp(self):
        # master を読まずに判定だけ検査する (I/O から切り離す)
        restamp._EBAY_OK.clear()
        restamp._EBAY_OK["pokemon_tcg"] = {"Sv2a: Pokemon Card 151", "S12a: Vstar Universe"}

    def tearDown(self):
        restamp._EBAY_OK.clear()

    def test_value_in_master_is_a(self):
        self.assertEqual(
            restamp._abc_state("pokemon_tcg", "Sv2a: Pokemon Card 151"), "a")

    def test_value_not_in_master_is_b(self):
        """master に無い値は canonical ではない (b)。ここを a と数えると誤報告になる."""
        self.assertEqual(
            restamp._abc_state("pokemon_tcg", "Start Deck 100 Battle Collection"), "b")

    def test_empty_is_c(self):
        for empty in ("", None):
            self.assertEqual(restamp._abc_state("pokemon_tcg", empty), "c")

    def test_unknown_category_is_never_a(self):
        """master を持たない category (= 凍結中) の値を canonical と数えない."""
        self.assertEqual(restamp._abc_state("gundam_tcg", "Whatever Set"), "b")

    def test_old_wrong_151_value_is_not_canonical(self):
        """`Pokemon 151` は master に無い = (a) ではない。今回の修正の核心."""
        self.assertEqual(restamp._abc_state("pokemon_tcg", "Pokemon 151"), "b")


if __name__ == "__main__":
    unittest.main()
