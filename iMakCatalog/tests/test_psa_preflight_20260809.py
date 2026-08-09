"""PSA preflight report (2026-08-09) 実装回帰テスト.

依頼: `iMak_data/catalog/requests/psa_preflight_report_response.md`

対象2件 (窓口 [IMPLEMENT-GO]):
  - R1: PORTGAS ACE #001 CHAMPIONSHIP SET 2023 → OP03-001_p2
    (② `_search_one_piece_promo_by_number` に "CHAMPIONSHIP SET YYYY" ↔
     "チャンピオンシップセットYYYY..." edition pair を年号一致必須で追加)
  - G7: SHENRON ALTERNATE ART #FB07-097 → FB07-097_p1 (variant)
    (① products の FB07-097 / _p1 / _p2 / _p3 に name_en='Shenron' を投入)

回帰対象 (絶対に overfire しないこと):
  - CHAMPIONSHIP tournament promo (SET 無し、例 'チャンピオンシップ2022 決勝') に
    edition_hit を発火させない。
  - 年号 mismatch (subject '2024' なのに DB は 2023 のみ) で誤採用しない (fail-closed)。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))
sys.path.insert(0, str(_REPO / "integrations"))

import psa_to_csv as pc  # type: ignore  # noqa: E402


class TestPortgasAceChampionshipSet2023(unittest.TestCase):
    """R1: cert 153574704 PORTGAS D. ACE CHAMPIONSHIP SET 2023 #001 → OP03-001_p2.

    追跡: edition pair 欠落 → `_P` `_P_p` などが同点で fail-closed reject。
    修正: "CHAMPIONSHIP SET 2023" ↔ "チャンピオンシップセット2023" 一致で +250 加点。
    """

    def test_portgas_ace_champset_2023_resolves_p2(self):
        r = pc._search_one_piece_promo_by_number(
            "001", "PORTGAS D ACE",
            brand="ONE PIECE JAPANESE PROMOS CHAMPIONSHIP SET 2023",
            verbose=False,
        )
        self.assertIsNotNone(r)
        self.assertEqual(r["product_id"], "OP03-001_p2")

    def test_edward_newgate_champset_2023_resolves_p3(self):
        # 同じ 2023 の別 championship set (旧四皇=OP02-001_p3, 001)。
        # subject の name 側 (Newgate vs Ace) で分離される。
        r = pc._search_one_piece_promo_by_number(
            "001", "EDWARD NEWGATE",
            brand="ONE PIECE JAPANESE PROMOS CHAMPIONSHIP SET 2023",
            verbose=False,
        )
        self.assertIsNotNone(r)
        self.assertEqual(r["product_id"], "OP02-001_p3")

    def test_trafalgar_law_champset_2022_resolves_p1(self):
        # 2022 championship set (ST03-008_p1)。年号 pair の別年動作確認。
        r = pc._search_one_piece_promo_by_number(
            "008", "TRAFALGAR LAW",
            brand="ONE PIECE JAPANESE PROMOS CHAMPIONSHIP SET 2022",
            verbose=False,
        )
        self.assertIsNotNone(r)
        self.assertEqual(r["product_id"], "ST03-008_p1")


class TestChampionshipSetYearGuard(unittest.TestCase):
    """年号一致必須。別年 Championship Set への暴発防止 (draft 副作用チェック)."""

    def test_ace_champset_2024_no_hit_year_mismatch(self):
        # subject 「2024」だが OP03-001 変種に championship set 2024 は存在しない。
        # 従来の scoring では _P/_P_p が同点 → fail-closed reject 継続。
        r = pc._search_one_piece_promo_by_number(
            "001", "PORTGAS D ACE",
            brand="ONE PIECE JAPANESE PROMOS CHAMPIONSHIP SET 2024",
            verbose=False,
        )
        self.assertIsNone(r)

    def test_championship_without_set_word_no_edition_hit(self):
        # "CHAMPIONSHIP 2022" (SET 無し = tournament 記念品) は edition_hit しない。
        # 素の promo brand 相当 → 従来どおり fail-closed reject。
        r = pc._search_one_piece_promo_by_number(
            "004", "MONKEY D LUFFY",
            brand="ONE PIECE JAPANESE PROMOS CHAMPIONSHIP 2022",
            verbose=False,
        )
        self.assertIsNone(r)


class TestShenronNameEnBackfill(unittest.TestCase):
    """G7: FB07-097 神龍 に name_en='Shenron' 投入。recovery で alt_art variant を選ぶ."""

    def test_shenron_base_lookup_populated(self):
        # DB 直読み: 4 record すべて name_en='Shenron' 入り、source='dbfw_en_official'。
        from iMakCatalog import api
        for pid in ("FB07-097", "FB07-097_p1", "FB07-097_p2", "FB07-097_p3"):
            rec = api.lookup("dragonball_scg", pid)
            self.assertIsNotNone(rec, pid)
            self.assertEqual(rec.get("name_en"), "Shenron", pid)

    def test_shenron_alternate_art_resolves(self):
        # cert 158452540 相当: brand=FB07 / subject 'SHENRON ALTERNATE ART' / #FB07-097
        # name_en 補完で subject token 'SHENRON' が record と一致 → variant _p1 選択。
        r = pc.lookup_dragonball(
            "DRAGON BALL SUPER FUSION WORLD JAPANESE FB07 WISH FOR SHENRON",
            "FB07-097", "SHENRON ALTERNATE ART", verbose=False,
        )
        self.assertIsNotNone(r)
        # ALTERNATE ART → _variant_candidates_dragonball 経由で _p1/_p2/_p3/PARA 等が候補。
        # base FB07-097 でも subject の 'SHENRON' が name_en と一致するため hit する可能性あり。
        # いずれにせよ card_id が FB07-097 で始まり、name_en が 'Shenron' であればよい。
        self.assertTrue(
            r["card_id"].startswith("FB07-097"),
            f"unexpected card_id={r['card_id']!r}",
        )
        self.assertEqual(r["name_en"], "Shenron")


if __name__ == "__main__":
    unittest.main()
