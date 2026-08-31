"""『ONE PIECE FILM RED』の3商品を取り違えないこと (2026-08-31).

きっかけ: `ONE PIECE JAPANESE FILM RED: ENCORE PACK-004` が pdca queue に
「catalog 未登録」で載った。実際は `ST11-004_p1 新時代` が在る。

## 何が誤りだったか (②引き方)

brand に set_code が無く (`FILM RED: ENCORE PACK`)、promo 経路にすら乗らず即 Skip。

## FILM RED は3商品ある — "FILM RED" だけで照合してはいけない

    『ONE PIECE FILM RED』入場者プレゼント アンコールパック   ST11-003_p1 / _004_p1 / _005_p1
    『ONE PIECE FILM RED』入場者プレゼント フィナーレセット   OP01-005_p1 ほか12枚
    プレミアムカードコレクション ‐ONE PIECE FILM RED ‐        OP01-005_p2 ほか12枚

商品名まで両側一致させて分ける (ENCORE PACK ↔ アンコールパック 等)。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))

from integrations.psa_to_csv import (  # noqa: E402
    extract_set_code_from_brand, lookup_one_piece)

ENCORE = "ONE PIECE JAPANESE FILM RED: ENCORE PACK"
ENCORE_SET = "『ONE PIECE FILM RED』入場者プレゼント アンコールパック"
FINALE_SET = "『ONE PIECE FILM RED』入場者プレゼント フィナーレセット"


class TestEncorePack(unittest.TestCase):
    def test_brand_reaches_the_promo_path(self):
        self.assertEqual(extract_set_code_from_brand(ENCORE), "P")

    def test_three_songs_resolve(self):
        for num, subject, pid in (("003", "BACKLIGHT", "ST11-003_p1"),
                                  ("004", "NEW GENESIS", "ST11-004_p1"),
                                  ("005", "I'M INVINCIBLE", "ST11-005_p1")):
            with self.subTest(card=f"#{num} {subject}"):
                r = lookup_one_piece(ENCORE, num, subject, verbose=False)
                self.assertIsNotNone(r, f"#{num} {subject} が候補に出ない")
                self.assertEqual(r.get("card_id"), pid)
                self.assertEqual(r.get("set_name_official"), ENCORE_SET)


class TestProductsAreNotMixed(unittest.TestCase):
    """同じ FILM RED でも別商品の行を返さないこと."""

    def test_finale_set_is_its_own_product(self):
        r = lookup_one_piece("ONE PIECE JAPANESE FILM RED: FINALE SET", "005", "UTA",
                             verbose=False) or {}
        self.assertEqual(r.get("set_name_official"), FINALE_SET)

    def test_encore_does_not_return_finale_rows(self):
        r = lookup_one_piece(ENCORE, "005", "I'M INVINCIBLE", verbose=False) or {}
        self.assertNotEqual(r.get("set_name_official"), FINALE_SET)


if __name__ == "__main__":
    unittest.main()
