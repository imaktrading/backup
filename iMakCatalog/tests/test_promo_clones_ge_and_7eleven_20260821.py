"""GIRLS EDITION ペローナ / 7-ELEVEN ルフィ の解決 (2026-08-21).

背景:
  - cert86028605 PERONA #086028605 は catalog に `OP01-077_GE` が無くて出せなかった。
  - cert145597172 / 155606219 MONKEY D. LUFFY #003 (Variety=7-ELEVEN CAMPAIGN) は
    **別絵柄の `ST13-003_P` (ドルトムント collab promo) を返していた** = 誤出品側。
    PSA スラブ実写で券面 'ST13-003' を確認し `ST13-003_7E01` を追加、
    edition pair ("7-ELEVEN", "セブンイレブン") で一意特定するようにした。

ここが壊れると「別のカードで出品する」に戻るので、番号・subject の分離まで固定する。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))

from integrations.psa_to_csv import lookup_one_piece  # noqa: E402

PROMOS = "ONE PIECE JAPANESE PROMOS"
GIRLS = "ONE PIECE JAPANESE PREMIUM CARD COLLECTION -GIRLS EDITION-"


def cid(brand: str, num: str, subject: str):
    r = lookup_one_piece(brand, num, subject, verbose=False)
    return r.get("card_id") if r else None


class TestGirlsEditionPerona(unittest.TestCase):
    def test_perona_077_resolves_to_ge_row(self):
        self.assertEqual(cid(GIRLS, "077", "PERONA"), "OP01-077_GE")

    def test_girls_edition_does_not_leak_to_plain_promo(self):
        """GIRLS EDITION 語が無ければ _GE には落ちない (両側一致必須の担保)."""
        self.assertNotEqual(cid(PROMOS, "077", "PERONA"), "OP01-077_GE")


class TestSevenElevenLuffy(unittest.TestCase):
    def test_luffy_003_resolves_to_seven_eleven_row(self):
        self.assertEqual(
            cid(PROMOS, "003", "MONKEY D. LUFFY 7-ELEVEN CAMPAIGN"), "ST13-003_7E01")

    def test_no_longer_returns_dortmund_promo(self):
        """回帰: 別絵柄の ST13-003_P を返さない (これが 2026-08-20 の実害)."""
        self.assertNotEqual(
            cid(PROMOS, "003", "MONKEY D. LUFFY 7-ELEVEN CAMPAIGN"), "ST13-003_P")

    def test_same_number_different_subject_stays_separate(self):
        """同じ #003 の 7-ELEVEN でも subject が違えばルフィに寄らない."""
        self.assertNotEqual(
            cid(PROMOS, "003", "EUSTASS KID 7-ELEVEN CAMPAIGN"), "ST13-003_7E01")

    def test_seven_eleven_pair_needs_both_sides(self):
        """7-ELEVEN 語が無い #003 ルフィは 7E01 に落ちない (両側一致必須)."""
        self.assertNotEqual(cid(PROMOS, "003", "MONKEY D. LUFFY"), "ST13-003_7E01")


if __name__ == "__main__":
    unittest.main()
