"""Gundam 新弾 (ST10/EB01/GD05) の set_code 抽出 + resolve 回帰テスト (2026-07-23).

ユーザー指示で新弾3セットを公式(gundam-gcg.com) + bandai_tcg_plus から取り込み。
- ST10 Generation Pulse (Starter, 6/27)
- EB01 Eternal Nexus (Extra Booster, 6/27) ← EB prefix を regex/keyword に新規追加
- GD05 Freedom Ascension (Booster, 7/25)
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
from iMakCatalog.ebay_filter_map import loader  # noqa: E402


class TestNewSetCodeExtraction(unittest.TestCase):
    def test_eb01_token_regex(self):
        # EB (Extra Booster) は 2026-07-23 追加。regex 直接一致。
        self.assertEqual(
            pc.extract_set_code_from_brand_gundam("GUNDAM JAPANESE EB01-ETERNAL NEXUS"), "EB01")

    def test_st10_token_regex(self):
        self.assertEqual(
            pc.extract_set_code_from_brand_gundam("GUNDAM JAPANESE ST10-GENERATION PULSE"), "ST10")

    def test_gd05_token_regex(self):
        self.assertEqual(
            pc.extract_set_code_from_brand_gundam("GUNDAM JAPANESE GD05-FREEDOM ASCENSION"), "GD05")

    def test_keyword_fallback_no_token(self):
        # code token を持たず英名のみの brand も keyword 逆引きで解決
        self.assertEqual(
            pc.extract_set_code_from_brand_gundam("GUNDAM CARD GAME ETERNAL NEXUS"), "EB01")
        self.assertEqual(
            pc.extract_set_code_from_brand_gundam("GUNDAM CARD GAME FREEDOM ASCENSION"), "GD05")
        self.assertEqual(
            pc.extract_set_code_from_brand_gundam("GUNDAM CARD GAME GENERATION PULSE"), "ST10")


class TestNewSetYamlMap(unittest.TestCase):
    def test_set_code_ebay_names(self):
        data = loader.load_yaml(loader.YAML_DIR / "gundam.yaml")
        m = {e["source"]: e["ebay"] for e in data["set_code"]}
        self.assertEqual(m["ST10"], "Generation Pulse")
        self.assertEqual(m["EB01"], "Eternal Nexus")
        self.assertEqual(m["GD05"], "Freedom Ascension")


if __name__ == "__main__":
    unittest.main()
