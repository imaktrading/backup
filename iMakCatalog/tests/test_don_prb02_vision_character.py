"""DON!! PRB02 character-key POC 回帰テスト (2026-07-25).

依頼: requests/2026-07-25_don_prb02_character_poc.md (HQ POC go)。
subject が generic 'DON!! CARD' で 90-way tie になる PRB02 DON を、cert cache の
Vision character (lookup_don の vision_character 引数) で一意解決する。
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

_BRAND = "ONE PIECE JAPANESE PRB02-PREMIUM BOOSTER -ONE PIECE CARD THE BEST- VOL.2"
_SUBJ = "DON!! CARD"


class TestDonPrb02VisionCharacter(unittest.TestCase):
    def test_buggy_resolves_to_buggy_record(self):
        r = pc.lookup_don(_BRAND, _SUBJ, vision_character="Buggy", verbose=False)
        self.assertIsNotNone(r)
        self.assertEqual(r["product_id"], "DON-PRB02-BUGGY-GOLD")

    def test_shanks_resolves_to_shanks_record(self):
        r = pc.lookup_don(_BRAND, _SUBJ, vision_character="Shanks", verbose=False)
        self.assertIsNotNone(r)
        self.assertEqual(r["product_id"], "DON-PRB02-SHANKS-GOLD")

    def test_no_vision_character_fails_closed(self):
        """vision 無 → 90-way tie で従来どおり解決不能 (推測で埋めない)."""
        r = pc.lookup_don(_BRAND, _SUBJ, verbose=False)
        self.assertIsNone(r)

    def test_unknown_character_fails_closed(self):
        """未登録キャラ → character 一致0 → hint scoring フォールスルー → None."""
        r = pc.lookup_don(_BRAND, _SUBJ, vision_character="Nami", verbose=False)
        self.assertIsNone(r)

    def test_buggy_does_not_fall_into_shanks(self):
        r = pc.lookup_don(_BRAND, _SUBJ, vision_character="Buggy", verbose=False)
        self.assertNotEqual((r or {}).get("product_id"), "DON-PRB02-SHANKS-GOLD")


if __name__ == "__main__":
    unittest.main()
