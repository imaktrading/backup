# -*- coding: utf-8 -*-
"""1〜2文字のカード名 (`N` / `AZ` / `GM`) が毎回 reject されないこと (2026-09-07).

依頼: `requests/2026-09-07_hq_subject_short_name_match.md`

## なぜ落ちていたか

`_subject_tokens` は PSA Subject から **3文字未満の語を捨てる**。カード名が `N` だと
subject 側から名前が消え、照合は subject → カタログ名 の一方向しか見ていなかったので、
`FA/N THE BEST OF XY` の `BEST` `XY` がカタログ名 `N` に含まれず **必ず不一致**になった。

該当するカタログ行は30行 (pokemon 17 / gundam 8 / yugioh 3 / one_piece 2)。

## どう直したか

**逆向き**を足した: カタログ名の語が subject の語に **全部** 含まれれば一致。
長さで捨てない。ID 完全一致の後の照合なので、名前検索フォールバックにはならない。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent))

from integrations import psa_to_csv as P  # noqa: E402

N = {"name": "N", "name_en": "N", "name_jp": "N", "product_id": "XY-139"}
GM = {"name": "GM", "name_en": "GM", "name_jp": "ジム", "product_id": "ST01-005"}
BEPO = {"name": "Bepo", "name_en": "Bepo", "name_jp": "ベポ", "product_id": "OP01-016"}


class TestShortName(unittest.TestCase):
    def test_one_letter_name_matches(self):
        for subj in ("FA/N THE BEST OF XY", "N-FULL ART", "N"):
            with self.subTest(subject=subj):
                self.assertTrue(P._record_name_matches_subject(N, subj))

    def test_two_letter_name_matches(self):
        self.assertTrue(P._record_name_matches_subject(GM, "GM HEROIC BEGINNINGS"))

    def test_other_card_still_rejected(self):
        """短い名前を通しても、**別のカードは通さない** (ここが緩むと誤出品)."""
        self.assertFalse(P._record_name_matches_subject(N, "GARDEVOIR BEST OF XY"))
        self.assertFalse(P._record_name_matches_subject(GM, "ZAKU II HEROIC BEGINNINGS"))

    def test_bonney_bepo_regression_holds(self):
        """2026-06 の Bonney→Bepo 事件が再発していないこと."""
        self.assertFalse(P._record_name_matches_subject(BEPO, "JEWELRY BONNEY"))
        self.assertTrue(P._record_name_matches_subject(BEPO, "BEPO ALTERNATE ART"))


if __name__ == "__main__":
    unittest.main()
