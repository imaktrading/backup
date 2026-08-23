"""焼き直しの「格下げ禁止」が **別の弾のセット名** まで守ってしまう問題を固定する.

経緯 (2026-08-23): 変換表を直して焼き直しても 12組が動かなかった。
`Sun & Moon - Team Up` は eBay の一覧に在る値 (= 英語版 SM9 の名前) なので、
格下げ禁止ガード「今の値が既に eBay の一覧に在るなら触らない」に守られていた。
だが日本語版 SM9 (タッグボルト) の刷りには誤り (ルール③) で、置き換えは格上げ。

例外の条件は監査 §0c と同じ:
    eBay に **その弾自身の値が在る** のに stored がそれでない、かつ derived がその弾の値

★守る側 (本来の格下げ禁止) を壊していないことも併せて固定する。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))
sys.path.insert(0, str(_REPO / "tools"))

import restamp_set_name_ebay as R  # type: ignore  # noqa: E402


class TestIsOtherSetValue(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        R._load_ebay_ok()

    def _f(self, pid, stored, derived, specs=None):
        return R._is_other_set_value("pokemon_tcg", pid, specs or {}, stored, derived)

    def test_english_set_name_on_jp_print_is_replaceable(self):
        # 英語版 SM9 の名前 → 日本語版 SM9 の値。格上げなので置き換えてよい
        self.assertTrue(self._f("SM9-001", "Sun & Moon - Team Up", "Sm9: Tag Bolt"))
        self.assertTrue(self._f("L3-B-001", "Triumphant", "L3: Clash at the Summit"))

    def test_sub_product_of_same_set_is_protected(self):
        # `S8a-P: …` は S8a の別商品。弾自身の名前で始まるので守る
        self.assertFalse(self._f(
            "S8a-P-010", "S8a-P: Promo Card Pack 25th Anniversary Edition",
            "S8a: 25th Anniversary Collection"))

    def test_no_own_code_value_means_protected(self):
        # その弾の値が eBay に無いなら、従来どおり守る (判断材料が無い)
        self.assertFalse(self._f("ZZ99-001", "Something", "Anything Else"))

    def test_derived_must_be_the_own_code_value(self):
        # derived がその弾の値でないなら守る (別の誤りに置き換えない)
        self.assertFalse(self._f("SM9-001", "Sun & Moon - Team Up", "Unified Minds"))


class TestLiveState(unittest.TestCase):
    """本番データ: 焼き直し済の弾が eBay の値になっていること."""

    def test_sm9_rows_use_jp_value(self):
        import json
        import sqlite3
        sys.path.insert(0, str(_REPO))
        import api  # noqa: E402
        db = sqlite3.connect(str(api._DB_PATH))
        vals = {json.loads(s)[  # noqa: E501
            "set_name_ebay"] for (s,) in db.execute(
            "SELECT specs FROM products WHERE category='pokemon_tcg' "
            "AND product_id LIKE 'SM9-%'")}
        db.close()
        self.assertNotIn("Sun & Moon - Team Up", vals,
                         "英語版セット名が残っている")
        self.assertIn("Sm9: Tag Bolt", vals)


if __name__ == "__main__":
    unittest.main()
