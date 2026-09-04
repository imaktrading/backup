"""PSA の母音抜き略記でも引けること (2026-09-04).

きっかけ: `cert139291730` が毎日 queue に「候補なし」で載っていた。
catalog には `SM9a-067 サーナイト&ニンフィアGX` が在るのに、PSA のラベルが

    FA/GRDVR. & SYLVN. GX NIGHT UNISON-HYPER

と **母音を落とした略記**で、名前照合が通らず reject されていた。

## 直し方 (狭く)

`.` で終わる大文字トークンだけ、母音を抜いた骨格で比べる
(`GRDVR` ↔ Gardevoir → `GRDVR`)。★`.` の無い語には使わない。
使うと別カードに当たる (この回帰も下で固定する)。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))

from integrations.psa_to_csv import lookup_pokemon  # noqa: E402

BRAND = "POKEMON JAPANESE SUN & MOON STRENGTH EXPANSION PACK NIGHT UNISON"


class TestAbbrev(unittest.TestCase):
    def test_vowel_dropped_subject_resolves(self):
        r = lookup_pokemon(BRAND, "067", "FA/GRDVR. & SYLVN. GX NIGHT UNISON-HYPER",
                           verbose=False)
        self.assertEqual((r or {}).get("card_id"), "SM9a-067")

    def test_plain_name_still_works(self):
        r = lookup_pokemon(BRAND, "067", "GARDEVOIR & SYLVEON GX", verbose=False)
        self.assertEqual((r or {}).get("card_id"), "SM9a-067")


class TestStillFailClosed(unittest.TestCase):
    def test_other_character_is_rejected(self):
        """回帰: 別キャラの subject は今までどおり弾く (略記ルールが緩すぎないこと)."""
        self.assertIsNone(lookup_pokemon(BRAND, "067", "PIKACHU", verbose=False))

    def test_dotless_abbrev_does_not_match(self):
        """`.` の無い語では骨格照合しない (誤マッチ防止)."""
        self.assertIsNone(lookup_pokemon(BRAND, "067", "GRDVR SYLVN", verbose=False))


if __name__ == "__main__":
    unittest.main()
