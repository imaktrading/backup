"""単行本『ONE PIECE CHOPPER’s 1』同梱 promo (cert 168544559) の引き当てを固定する.

経緯: PSA 目視 review で cert 168544559 が expected=null → 該当なしで落ちていた
(2026-08-23 08:17)。真因は catalog に受け皿の行が無かったこと (判定①)。
`EB02-003_CH01` を追加した後も **通常版 EB02-003 に解決したまま**だったため
(suffix 無し base が +10、`_CH01` は 0点)、edition pair
("CHOPPER'S 1", "CHOPPER’s 1") を _search_one_piece_promo_by_number に足した。

★apostrophe が両側で違う: PSA は ASCII "'"、集英社の公式書名は U+2019 "’"。
★巻数 " 1" を含める: 2巻以降の同梱 promo と混ざらないようにするため。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))
sys.path.insert(0, str(_REPO / "integrations"))

import psa_to_csv as pc  # type: ignore  # noqa: E402


def _pid(brand: str, card_no: str, subject: str):
    rec = pc.lookup_one_piece(brand, card_no, subject, verbose=False)
    return (rec or {}).get("card_id")


class TestChoppers1BundlePromo(unittest.TestCase):
    def test_cert_168544559_resolves_to_ch01(self):
        self.assertEqual(
            _pid("ONE PIECE JAPANESE PROMOS", "003",
                 "TONY TONY CHOPPER ONE PIECE CHOPPER'S 1"),
            "EB02-003_CH01",
        )

    def test_booster_print_unchanged(self):
        # 弾コードが brand に在る通常版は base のまま (promo に吸われない)
        self.assertEqual(
            _pid("ONE PIECE JAPANESE EB02-ANIME 25TH COLLECTION", "003",
                 "TONY TONY CHOPPER"),
            "EB02-003",
        )

    def test_generic_chopper_promo_still_failclosed(self):
        # edition 句の無い汎用 promo brand は従来どおり reject (over-fire していない)
        self.assertIsNone(
            _pid("ONE PIECE JAPANESE PROMOS", "006", "TONY TONY CHOPPER")
        )

    def test_seven_eleven_pair_unaffected(self):
        # 同じ #003 の 7-ELEVEN promo が奪われていないこと (直前の pair の回帰)
        self.assertEqual(
            _pid("ONE PIECE JAPANESE PROMOS", "003",
                 "MONKEY D. LUFFY 7-ELEVEN CAMPAIGN"),
            "ST13-003_7E01",
        )


if __name__ == "__main__":
    unittest.main()
