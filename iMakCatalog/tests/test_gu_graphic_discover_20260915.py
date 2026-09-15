"""GU のグラフィックT 掘り起こしの回帰 (2026-09-15).

- 公式のパンくずで「大人のグラフィックT」だけを対象にする (キッズ・他の衣類は入れない)
- 公式から消えた商品は「画像だけの行」で、出品しない印を付ける
- 判定は1件ずつ追記し、再実行は判定済みを飛ばす (失敗した判定は飛ばさない)
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "scrapers")]

import gu_graphic_discover as G  # noqa: E402


class TestTarget(unittest.TestCase):
    def test_adult_graphic_tee(self):
        self.assertTrue(G.is_target({"category": "graphict", "class": "tops", "gender": "MEN"}))
        self.assertTrue(G.is_target({"category": "graphict", "class": "tops", "gender": "WOMEN"}))

    def test_kids_and_other_items_excluded(self):
        self.assertFalse(G.is_target({"category": "graphict", "class": "tops", "gender": "KIDS"}))
        self.assertFalse(G.is_target({"category": "widepants", "class": "bottoms", "gender": "MEN"}))
        self.assertFalse(G.is_target({"category": "", "class": "", "gender": ""}))


class TestVerdictResume(unittest.TestCase):
    def test_errors_are_not_treated_as_done(self):
        with tempfile.TemporaryDirectory() as d:
            G.VERDICTS = Path(d) / "_gu_verdicts.jsonl"
            G.RAW = Path(d)
            G.record({"pid": "E000001-000", "category": "graphict", "class": "tops", "gender": "MEN"})
            G.record({"pid": "E000002-000", "error": True})
            done = G.load_verdicts()
            self.assertIn("E000001-000", done)
            self.assertNotIn("E000002-000", done)


class TestGoneRowsNotForListing(unittest.TestCase):
    def test_images_only_rows_carry_flag(self):
        src = (ROOT / "scrapers" / "gu_graphic_discover.py").read_text(encoding="utf-8")
        self.assertIn('"data_level": "images_only"', src)
        self.assertIn('"not_for_listing": True', src)


if __name__ == "__main__":
    unittest.main()
