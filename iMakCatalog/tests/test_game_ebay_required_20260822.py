"""Game (eBay で唯一の必須項目) が空欄にならないこと (2026-08-22).

2026-08-22 実測: scraper の stamp 漏れで 2,835行が空欄だった。
Game は eBay 183454 で **唯一の必須項目**なので、空欄のまま出品に流れてはいけない。

守る不変条件:
  A) TCG 5カテゴリで specs.game_ebay が空の行が 0
  B) api.lookup() は specs に無くても category から埋めて返す (scraper が忘れても空にならない)
  C) 未知 category は None (fail-closed。推測で埋めない)
"""
from __future__ import annotations

import json
import sqlite3
import sys
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO.parent))
sys.path.insert(0, str(_REPO))
import api  # noqa: E402

TCG = ("pokemon_tcg", "one_piece_tcg", "gundam_tcg", "dragonball_scg", "yugioh_tcg")


class TestGameNotBlank(unittest.TestCase):
    def test_no_blank_game_in_tcg(self):
        con = sqlite3.connect(str(api._DB_PATH))
        try:
            for cat in TCG:
                n = 0
                for (sp,) in con.execute("SELECT specs FROM products WHERE category=?", (cat,)):
                    d = json.loads(sp) if sp else {}
                    if not (d.get("game_ebay") or "").strip():
                        n += 1
                self.assertEqual(n, 0, f"{cat} の Game 空欄 = {n} (必須項目なので 0 でなければならない)")
        finally:
            con.close()


class TestDeriveGame(unittest.TestCase):
    def test_known_categories(self):
        self.assertEqual(api.derive_game_ebay("one_piece_tcg"), "One Piece CCG")
        self.assertEqual(api.derive_game_ebay("pokemon_tcg"), "Pokémon TCG")
        self.assertEqual(api.derive_game_ebay("yugioh_tcg"), "Yu-Gi-Oh! TCG")

    def test_gundam_stays_free_text(self):
        """eBay の Game 一覧に無いが、'Gundam War TCG' (別ゲーム) に寄せてはいけない."""
        self.assertEqual(api.derive_game_ebay("gundam_tcg"), "Gundam Card Game")

    def test_unknown_category_is_none(self):
        """推測で埋めない."""
        self.assertIsNone(api.derive_game_ebay("montbell"))
        self.assertIsNone(api.derive_game_ebay("nope"))


if __name__ == "__main__":
    unittest.main()
