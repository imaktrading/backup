"""ストレージボックスセットの7枚を PSA から引けること (2026-08-28).

依頼: `requests/2026-08-27_hq_storagebox_set_resolver.md` (初出 2026-05-25、cert 4件、
pdca queue 306/595/607/610/617 に割れて再発)。

判定 (1丁目1番地): ①カタログ正 (14行 画像つきで在る) / ②引き方が誤り。

## 何が誤りだったか

PSA brand `... PREMIUM BOOSTER -ONE PIECE CARD THE BEST- STORAGE BOX SET` に
"ONE PIECE CARD THE BEST" が入っているので、marketing 表が `PRB01` を作り
`PRB01-004` で Skip していた (= 偽の「catalog 未収録」)。
実際は **収録元セットごとに set_code が違う合本** (ST16/ST17/OP08/OP05/EB01/ST01/ST10)
なので、brand から set_code は作れない。番号 + 商品名の照合で解く。

★#001 は罠: `ST16-001_p1/_p2` (合本のウタ) と `ST11-001` (Side ウタ) が同名同番号。
  合本側に +30 の qualifier が無いと、suffix 無し base の +10 が勝って別カードを返す。
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

BRAND = "ONE PIECE JAPANESE PREMIUM BOOSTER -ONE PIECE CARD THE BEST- STORAGE BOX SET"
SET_OFFICIAL = "プレミアムブースター ONE PIECE CARD THE BEST ストレージボックスセット"

CARDS = [
    ("004", "BOA HANCOCK", "ST17-004"),
    ("105", "JEWELRY BONNEY", "OP08-105"),
    ("001", "UTA", "ST16-001"),
    ("007", "NAMI", "ST01-007"),
    ("013", "EUSTASS KID", "ST10-013"),
    ("093", "ROB LUCCI", "OP05-093"),
    ("043", "SPANDINE", "EB01-043"),
]


class TestBrandIsNotPrb01(unittest.TestCase):
    def test_set_code_is_promo_not_prb01(self):
        """brand から set_code を作らない (作ると PRB01-004 で Skip する)."""
        self.assertEqual(extract_set_code_from_brand(BRAND), "P")

    def test_plain_the_best_brand_still_maps_to_prb01(self):
        """回帰: ストレージボックスセットでない PRB-01 の brand は今までどおり."""
        self.assertEqual(
            extract_set_code_from_brand("ONE PIECE JAPANESE ONE PIECE CARD THE BEST"),
            "PRB01")


class TestResolves(unittest.TestCase):
    def test_all_seven_resolve_to_this_product(self):
        for num, subject, base in CARDS:
            with self.subTest(card=f"#{num} {subject}"):
                r = lookup_one_piece(BRAND, num, subject, verbose=False)
                self.assertIsNotNone(r, f"#{num} {subject} が候補に出ない")
                self.assertEqual(r.get("set_name_official"), SET_OFFICIAL,
                                 f"別商品の行を返している: {r.get('card_id')}")
                self.assertTrue(str(r.get("card_id", "")).startswith(base + "_"),
                                f"{r.get('card_id')} は {base} の変種ではない")


class TestUtaTrap(unittest.TestCase):
    """#001 ウタ は同名同番号の別カード (ST11-001 Side ウタ) を返さないこと."""

    def test_does_not_return_side_uta(self):
        r = lookup_one_piece(BRAND, "001", "UTA", verbose=False) or {}
        self.assertNotEqual(r.get("card_id"), "ST11-001",
                            "Side ウタ (別商品) を返している = 誤出品")


if __name__ == "__main__":
    unittest.main()
