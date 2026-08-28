"""DON カードは brand 側の商品名でも引けること (2026-08-28).

きっかけ: cert156843873 (PSA brand `ONE PIECE JAPANESE PREMIUM CARD COLLECTION
-ONE PIECE DAY'24-` / subject `DON!! CARD`) が pdca queue に
「recovery不一致 (set_code=P)」で毎日積まれていた。

## 何が誤りだったか (②引き方)

DON の照合は **subject だけ**を見ていた。PSA は DON の商品名を **brand 側**に置き、
subject は `DON!! CARD` としか書かないことが多いので score=0 → 267候補すべて fail-closed。
記号の違い (`DAY'24` と `DAY 24`) でも当たらなかった。

## 直した点

1. 照合先を brand + subject にした (記号は `_don_norm` で吸収)
2. 同点になったら **brand が商品名を言い当てているもの**で分ける
   (DAY'24 は SPECIAL LIVE Day1 / Day2 / プレミアムドンコレクション の3枚が同点になる。
    brand の PREMIUM ... COLLECTION で3枚目に決まる)

★カタログ側は正しい。現物 (スラブ実写) と `DON-OP-DAY-24-003` の絵は一致、
  `-001` は GRe4N BOYZ の別絵柄で明確に別物。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))

from integrations.psa_to_csv import lookup_don, _don_norm  # noqa: E402

DAY24_BRAND = "ONE PIECE JAPANESE PREMIUM CARD COLLECTION -ONE PIECE DAY'24-"


class TestNormalize(unittest.TestCase):
    def test_apostrophe_and_dash_are_absorbed(self):
        self.assertEqual(_don_norm("-ONE PIECE DAY'24-"), "ONE PIECE DAY 24")
        self.assertEqual(_don_norm("ONE PIECE DAY’24"), "ONE PIECE DAY 24")


class TestDay24(unittest.TestCase):
    def test_resolves_to_premium_don_collection(self):
        r = lookup_don(DAY24_BRAND, "DON!! CARD", None, verbose=False)
        self.assertIsNotNone(r, "cert156843873 の DON が引けない")
        self.assertEqual(r.get("product_id"), "DON-OP-DAY-24-003")

    def test_does_not_return_special_live_cards(self):
        """同じ DAY'24 でも SPECIAL LIVE の2枚 (別絵柄) を返さない."""
        r = lookup_don(DAY24_BRAND, "DON!! CARD", None, verbose=False) or {}
        self.assertNotIn(r.get("product_id"),
                         ("DON-OP-DAY-24-001", "DON-OP-DAY-24-002"))


class TestStillFailClosed(unittest.TestCase):
    """回帰: 手がかりが無い brand は今までどおり出さない."""

    def test_generic_brand_returns_none(self):
        self.assertIsNone(
            lookup_don("ONE PIECE JAPANESE PROMOS", "DON!! CARD", None, verbose=False))

    def test_non_don_subject_returns_none(self):
        self.assertIsNone(lookup_don(DAY24_BRAND, "MONKEY D. LUFFY", None, verbose=False))


if __name__ == "__main__":
    unittest.main()
