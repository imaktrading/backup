"""PB01 プレミアムグッズセット (ガンダムW) の resolve 回帰テスト (2026-07-23).

依頼: requests/2026-07-23_auto_catalog_add_gundam_tcg.md (cert154708671 #100)。
PB01 は複数 base セット (GD01-100 / ST02-010) の再録のため、brand→set_code 逆引き
(PREMIUM GOODS+WING→ST02) では #100 が ST02-100 に化けて miss していた。
番号→base pid の明示 map (_PB01_BASE_BY_NUMBER) で解決。
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

_BRAND = "GUNDAM JAPANESE PB01-PREMIUM GOODS SET -MOBILE SUIT GUNDAM WING-"


class TestPb01Resolve(unittest.TestCase):
    def test_cert154708671_show_of_resolve_100(self):
        """#100 → GD01-100_PB01 (U+)。旧実装は ST02-100 を探して skip していた."""
        r = pc.lookup_gundam(_BRAND, "100", "A SHOW OF RESOLVE", verbose=False)
        self.assertIsNotNone(r)
        self.assertEqual(r.get("card_id"), "GD01-100_PB01")
        self.assertEqual(r.get("rarity"), "U+")

    def test_cert154708676_heero_yuy_010_regression(self):
        """#010 → ST02-010_PB01 (7/10 経路の回帰) + rarity 空だった穴が C+ で埋まっている."""
        r = pc.lookup_gundam(_BRAND, "010", "HEERO YUY", verbose=False)
        self.assertIsNotNone(r)
        self.assertEqual(r.get("card_id"), "ST02-010_PB01")
        self.assertEqual(r.get("rarity"), "C+")

    def test_base_lookups_unaffected(self):
        r = pc.lookup_gundam("GUNDAM JAPANESE GD01-NEWTYPE RISING", "100",
                             "A SHOW OF RESOLVE", verbose=False)
        self.assertEqual(r.get("card_id"), "GD01-100")

    def test_pb01_unknown_number_fails_closed(self):
        """PB01 に存在しない番号は resolve しない (fail-closed)."""
        r = pc.lookup_gundam(_BRAND, "999", "NONEXISTENT CARD", verbose=False)
        self.assertIsNone(r)

    def test_pb01_set_name_is_promo_cards_not_base(self):
        """2026-07-24 HQ依頼: PB01 再録の set は base 弾名でなく Promo Cards。
        _row_to_dict が set_name_official 未登録時に product_id prefix(ST02/GD01)へ
        fallback して 'Wings of Advance'/'Newtype Rising' を返すと PSA brand(PB01)と
        不一致→selfcheck 拒否。yaml に PB01 set マッピングを追加して整合させた。"""
        for num, subj in [("010", "HEERO YUY"), ("100", "A SHOW OF RESOLVE")]:
            r = pc.lookup_gundam(_BRAND, num, subj, verbose=False)
            self.assertEqual(r.get("set_name_ebay"), "Promo Cards", num)


if __name__ == "__main__":
    unittest.main()
