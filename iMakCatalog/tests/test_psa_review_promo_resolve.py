"""PSA pre-flight REVIEW promo resolver (2026-06-12).

preflight report (psa_preflight_report.md) の REVIEW 5件のうち、
**ブランド/サブジェクトで variant が一意に決まる 2件のみ** を resolver で解決し、
**曖昧な 2件は fail-closed reject 維持** であることを固定する。

確定 (resolve させる):
  - cert 148642488 ZORO-JUUROU 2ND ANV. COMPLETE GUIDE #067 → OP05-067_p2
    (#067 候補中 official に "COMPLETE GUIDE" を持つのは _p2 のみ = 一意)
  - cert 142931332 PIKACHU V 25TH ANNIV GOLDEN BOX #005 → S8a-G-005
    (GOLDEN BOX は S8a-G 専用サブセット。plain S8a-005=Lugia と衝突回避)

曖昧 (reject 維持 = 誤出品防止):
  - cert 152816423 TONY TONY CHOPPER LET'S START CP PR PCK #006
    (EB01-006 系 promo 変種 _P/_P_P/_P_treasure が複数、brand で一意化不能)
  - cert 86915908 CHARLOTTE PUDDING #008
    (ST07-008 系 promo 変種 _P/_P_D/_p1/_p3 が複数、brand で一意化不能)

注: 生 PSA brand/subject は HQ 側 (PSA API) にあり worktree 内に無いため、
    本 test の brand/subject は preflight report 由来の再構成。両側一致 (edition pair)
    設計のため、token が brand/subject どちら側でも hay 照合で拾える。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))
sys.path.insert(0, str(_REPO / "integrations"))

import psa_to_csv as pc  # type: ignore  # noqa: E402


class TestOnePieceCompleteGuide(unittest.TestCase):
    """ZORO 2nd Anniversary Complete Guide promo (cert 148642488)."""

    def test_zoro_complete_guide_resolves_p2(self):
        r = pc._search_one_piece_promo_by_number(
            "067", "ZORO JUUROU",
            brand="ONE PIECE JAPANESE PROMOS 2ND ANV. COMPLETE GUIDE",
            verbose=False,
        )
        self.assertIsNotNone(r)
        self.assertEqual(r["product_id"], "OP05-067_p2")

    def test_zoro_plain_promo_stays_reject(self):
        # "COMPLETE GUIDE" を含まない汎用 promo brand では一意化できず reject (over-fire しない)
        r = pc._search_one_piece_promo_by_number(
            "067", "ZORO JUUROU",
            brand="ONE PIECE JAPANESE PROMOS",
            verbose=False,
        )
        self.assertIsNone(r)


class TestOnePieceAmbiguousStayReject(unittest.TestCase):
    """曖昧 promo は fail-closed reject 維持 (誤出品防止)."""

    def test_chopper_lets_start_reject(self):
        r = pc._search_one_piece_promo_by_number(
            "006", "TONY TONY CHOPPER",
            brand="ONE PIECE JAPANESE PROMOS LET'S START CARDGAME PROMOTION PACK",
            verbose=False,
        )
        self.assertIsNone(r)

    def test_charlotte_pudding_reject(self):
        r = pc._search_one_piece_promo_by_number(
            "008", "CHARLOTTE PUDDING",
            brand="ONE PIECE JAPANESE PROMOS",
            verbose=False,
        )
        self.assertIsNone(r)


class TestPokemonGoldenBox(unittest.TestCase):
    """25th Anniversary Golden Box = S8a-G 専用サブセット (cert 142931332)."""

    def test_golden_box_set_code_is_s8ag(self):
        code = pc.extract_set_code_from_brand_pokemon(
            "POKEMON JAPANESE 25TH ANNIVERSARY GOLDEN BOX"
        )
        self.assertEqual(code, "S8a-G")

    def test_golden_box_pikachu_v_resolves(self):
        r = pc.lookup_pokemon(
            "POKEMON JAPANESE 25TH ANNIVERSARY GOLDEN BOX", "005",
            "PIKACHU V", verbose=False,
        )
        self.assertIsNotNone(r)
        self.assertEqual(r["card_id"], "S8a-G-005")
        self.assertEqual(r["name_en"], "Pikachu V")

    def test_plain_25th_collection_unaffected(self):
        # 通常弾 25TH ANNIVERSARY COLLECTION は S8a のまま (回帰防止)。S8a-005=Lugia
        code = pc.extract_set_code_from_brand_pokemon(
            "POKEMON JAPANESE 25TH ANNIVERSARY COLLECTION"
        )
        self.assertEqual(code, "S8a")
        r = pc.lookup_pokemon(
            "POKEMON JAPANESE 25TH ANNIVERSARY COLLECTION", "005",
            "LUGIA", verbose=False,
        )
        self.assertEqual(r["card_id"], "S8a-005")


if __name__ == "__main__":
    unittest.main()
