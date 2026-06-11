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
    """25th Anniversary Golden Box = S8a-G 専用サブセット (brand-path).

    ※ 元 cert 142931332 は実際には ASIA 版 (brand=POKEMON ASIA 25TH ANNIVERSARY PROMO /
      GOLDEN BOX は subject 側) で、本 brand-path は no-op = reject。下の
      TestPokemonGoldenBoxAsiaReject 参照。本 class は JP-brand(GOLDEN BOX が brand 側)
      に対する brand-path 配線の正しさを固定する。
    """

    def test_golden_box_set_code_is_s8ag(self):
        code = pc.extract_set_code_from_brand_pokemon(
            "POKEMON JAPANESE 25TH ANNIVERSARY GOLDEN BOX"
        )
        self.assertEqual(code, "S8a-G")

    def test_golden_box_pikachu_v_resolves_jp_brand(self):
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


class TestPokemonGoldenBoxAsiaReject(unittest.TestCase):
    """cert 142931332 実物 = ASIA 版 Golden Box → reject が正 (HQ raw dump 2026-06-12).

    brand=POKEMON ASIA 25TH ANNIVERSARY PROMO / subject に GOLDEN BOX。
    25th Golden Box は JP/繁中/韓/尼版が同一 S8a-G 番号だが言語が異なる(Bulbapedia/TCGplayer)。
    catalog S8a-G-005 は日本語 record のため、ASIA cert を解決すると Language 誤り
    (出品の正確性違反)。GOLDEN BOX が brand 側に無いので brand-path は構造的に no-op =
    言語誤りを回避する fail-closed。catalog に ASIA言語版が入るまで reject 維持が正。
    """

    def test_asia_golden_box_rejects(self):
        r = pc.lookup_pokemon(
            "POKEMON ASIA 25TH ANNIVERSARY PROMO", "005",
            "PIKACHU V 25TH ANNIV-GOLDEN BOX", verbose=False,
        )
        self.assertIsNone(r)


class TestPokemonPromoCardPack25th(unittest.TestCase):
    """cert 77429277 Shining Magikarp = S8a-P (プロモカードパック25th, brand-path).

    HQ raw dump: brand=POKEMON JAPANESE PROMO CARD PACK 25TH ANNIVERSARY EDITION
    (GOLDEN BOX/Pikachu と違い set 句が brand 側 → brand-path で配線可)。
    record S8a-P-010 は収録済(共有DB)。
    """

    def test_promo_card_pack_set_code_is_s8ap(self):
        code = pc.extract_set_code_from_brand_pokemon(
            "POKEMON JAPANESE PROMO CARD PACK 25TH ANNIVERSARY EDITION"
        )
        self.assertEqual(code, "S8a-P")

    def test_shining_magikarp_resolves(self):
        r = pc.lookup_pokemon(
            "POKEMON JAPANESE PROMO CARD PACK 25TH ANNIVERSARY EDITION", "010",
            "SHINING MAGIKARP-HOLO PCP 25TH ANNIVERSARY ED.", verbose=False,
        )
        self.assertIsNotNone(r)
        self.assertEqual(r["card_id"], "S8a-P-010")


if __name__ == "__main__":
    unittest.main()
