"""数字を持たない set_code (スターターセット等) を brand の先頭から拾う (2026-08-31).

きっかけ: `POKEMON JAPANESE MBG-MEGA STARTER SET MEGA GENGAR EX #003` が
pdca queue に「catalog 未登録」で載った。実際は `MBG-003 メガゲンガーex` が在る。

## 何が誤りだったか (②引き方)

数字を持たない set_code は **1行ずつ手で足す表** (`MBD` / `CLF` / `CLK` / `CLL`) でしか
拾えず、`MBG` の足し忘れでスターターセット8枚が丸ごと引けなかった。
足し忘れは今後も起きるので、**PSA の書き方から拾って catalog で裏を取る**形にした。

★裏取り必須 (fail-closed): catalog にその set_code の行が無ければ None のまま。
★綴りは catalog のものを返す (`DPtP` / `HSm` のような大小混在があるため、
  大文字のまま返すと product_id の完全一致 lookup が外れる)。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))

from integrations.psa_to_csv import (  # noqa: E402
    extract_set_code_from_brand_pokemon, lookup_pokemon)


class TestStarterSetCodes(unittest.TestCase):
    def test_mbg_is_extracted_and_resolves(self):
        b = "POKEMON JAPANESE MBG-MEGA STARTER SET MEGA GENGAR EX"
        self.assertEqual(extract_set_code_from_brand_pokemon(b), "MBG")
        r = lookup_pokemon(b, "003", "M GENGAR EX", verbose=False)
        self.assertEqual((r or {}).get("card_id"), "MBG-003")

    def test_mbd_still_works(self):
        """回帰: 表に手で足してあった分は今までどおり."""
        self.assertEqual(
            extract_set_code_from_brand_pokemon(
                "POKEMON JAPANESE MBD-MEGA STARTER SET MEGA DIANCIE EX"), "MBD")


class TestFailClosed(unittest.TestCase):
    def test_unknown_code_is_not_invented(self):
        """catalog に無い set_code は拾わない (推測で product_id を作らない)."""
        self.assertIsNone(
            extract_set_code_from_brand_pokemon("POKEMON JAPANESE ZZZ-NOT A REAL SET"))

    def test_mcdonalds_is_still_skipped(self):
        """回帰: McDonald's promo は従来どおり None (番号衝突を避けるため)."""
        self.assertIsNone(
            extract_set_code_from_brand_pokemon("POKEMON JAPANESE MCDONALD'S PROMO"))


if __name__ == "__main__":
    unittest.main()
