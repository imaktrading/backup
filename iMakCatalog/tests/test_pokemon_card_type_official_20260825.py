"""ポケモンの種別を公式の見出しから取ることを固定する.

経緯 (2026-08-25): 取り込みが **カード名に「エネルギー」が入っているか**で種別を決めていた。

    if hp: Pokémon / elif "エネルギー" in name: Energy / else: Trainer

その結果、グッズの「エネルギー回収」「エネルギーつけかえ」等 127行が Energy になっていた。
しかも `Energy` は **eBay の Card Type に存在しない値**だった (正は Energy-Basic / -Special)。
Stage (08-23) / タイプ (08-23) と同じ形。

公式は種別を見出しに出す (`<h2>グッズ</h2>`)。語彙は7つだけで、eBay の値と1対1で対応する。
"""
from __future__ import annotations

import json
import sqlite3
import sys
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))
sys.path.insert(0, str(_REPO / "tools"))
sys.path.insert(0, str(_REPO / "scrapers"))

import api  # type: ignore  # noqa: E402
import set_name_integrity_audit as A  # type: ignore  # noqa: E402
from pokemon_tcg import _CARD_TYPE_TO_EBAY  # type: ignore  # noqa: E402


class TestMapping(unittest.TestCase):
    def test_every_official_word_maps_to_an_ebay_value(self):
        ok = A._load_card_types().get("pokemon_tcg", set())
        self.assertTrue(ok, "eBay の Card Type 値表が読めていない")
        bad = sorted(v for v in _CARD_TYPE_TO_EBAY.values() if v not in ok)
        self.assertEqual(bad, [], f"eBay に無い値に写している: {bad}")

    def test_energy_is_split(self):
        self.assertEqual(_CARD_TYPE_TO_EBAY["基本エネルギー"], "Energy-Basic")
        self.assertEqual(_CARD_TYPE_TO_EBAY["特殊エネルギー"], "Energy-Special")

    def test_trainer_is_split(self):
        self.assertEqual(_CARD_TYPE_TO_EBAY["グッズ"], "Trainer-Item")
        self.assertEqual(_CARD_TYPE_TO_EBAY["サポート"], "Trainer-Supporter")
        self.assertEqual(_CARD_TYPE_TO_EBAY["スタジアム"], "Trainer-Stadium")
        self.assertEqual(_CARD_TYPE_TO_EBAY["ポケモンのどうぐ"], "Pokémon Tool")


class TestScraperAnchors(unittest.TestCase):
    def test_no_name_based_inference(self):
        src = (_REPO / "scrapers" / "pokemon_tcg.py").read_text(encoding="utf-8")
        self.assertNotIn('elif "エネルギー" in name:', src,
                         "カード名から種別を決める旧実装が残っている")
        self.assertIn("card_type_official", src, "公式見出しから取っていない")


class TestLiveData(unittest.TestCase):
    def test_no_bare_energy_value(self):
        db = sqlite3.connect(str(api._DB_PATH))
        try:
            n = db.execute(
                "SELECT COUNT(*) FROM products WHERE category='pokemon_tcg' "
                "AND json_extract(specs,'$.card_type_ebay')='Energy'").fetchone()[0]
        finally:
            db.close()
        self.assertEqual(n, 0, "eBay に無い値 'Energy' が残っている")

    def test_energy_items_are_trainer(self):
        # 「エネルギー回収」等はグッズ。名前で判定していた頃は Energy になっていた
        for pid in ("MC-636", "M3-101"):
            rec = api.lookup("pokemon_tcg", pid)
            if rec is None:
                continue
            self.assertEqual(rec["specs"].get("card_type_ebay"), "Trainer-Item", pid)

    def test_audit_section_is_zero(self):
        res = A.audit(["pokemon_tcg"])
        self.assertEqual(res.card_type_unknown, [],
                         f"eBay の値表に無い Card Type {len(res.card_type_unknown)} 行")


if __name__ == "__main__":
    unittest.main()
