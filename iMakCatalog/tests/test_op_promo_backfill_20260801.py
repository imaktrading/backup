"""2026-08-01 窓口GO: OP promo set_name_ebay backfill 21件 の回帰テスト.

- 4 promo set の空欄行が 'Promo Cards' で埋まっている (backfill 済)。
- 【B】 OP05-119_p8 (English 2nd ANNIVERSARY SET) は mapping 無し = 空のまま (fail-closed)。
- 327 Ultra Prism 誤マップ (pokemon_tcg) は埋め戻されず空欄のまま。
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import unittest

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO.parent))
sys.path.insert(0, str(_REPO))
import api  # type: ignore  # noqa: E402


class TestOpPromoBackfill(unittest.TestCase):
    def test_backfilled_rows_are_promo_cards(self):
        for pid in ("ST01-006_p1", "OP01-005_p2", "OP03-044_p2", "OP12-031_p2"):
            rec = api.lookup(category="one_piece_tcg", product_id=pid)
            self.assertIsNotNone(rec, pid)
            self.assertEqual(rec["specs"].get("set_name_ebay"), "Promo Cards", pid)
            self.assertEqual(rec["specs"].get("set_name_ebay_source"),
                             "filter_map_backfill_20260801", pid)

    def test_2nd_anniversary_stays_empty_no_map(self):
        """【B】 mapping 無し → derive None、空のまま (推測で埋めない)。"""
        self.assertIsNone(
            api.derive_set_name_ebay(
                "one_piece_tcg",
                "ONE PIECE カードゲーム English 2nd ANNIVERSARY SET", "OP05-119_p8"))
        rec = api.lookup(category="one_piece_tcg", product_id="OP05-119_p8")
        self.assertFalse((rec or {}).get("specs", {}).get("set_name_ebay"))

    def test_ultra_prism_327_not_refilled(self):
        """327 (pokemon_tcg 誤マップ空欄化) が backfill で埋め戻されていない。"""
        con = sqlite3.connect(str(api._DB_PATH))
        n = con.execute(
            "SELECT count(*) FROM products WHERE "
            "json_extract(specs,'$.set_name_ebay_source')="
            "'blanked_by_ultra_prism_mismap_20260731'").fetchone()[0]
        con.close()
        self.assertEqual(n, 327)


if __name__ == "__main__":
    unittest.main()
