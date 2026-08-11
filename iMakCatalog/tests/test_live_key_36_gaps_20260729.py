"""2026-07-29 live cert 残 36件 gap 対応の回帰テスト.

- character_name backfill (DBSCG _p1 は base から / OP P- は name_en から)
- OP promo/event set_name_ebay yaml マッピング
"""
from __future__ import annotations
import sys
from pathlib import Path
_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO.parent)); sys.path.insert(0, str(_REPO)); sys.path.insert(0, str(_REPO / "integrations"))
import unittest
from iMakCatalog import api


class TestCharacterNameBackfill(unittest.TestCase):
    def test_dbscg_p1_character_from_base(self):
        for pid, ch in [("FB01-140_p1", "Son Gohan : Childhood"),
                        ("SB02-058_p1", "King Piccolo"), ("SB02-060_p1", "Red Ribbon Robot")]:
            rec = api.lookup(category="dragonball_scg", product_id=pid)
            self.assertEqual(rec["specs"].get("character_name"), ch, pid)

    def test_op_promo_character_from_nameen(self):
        for pid, ch in [("P-033", "Monkey D. Luffy"), ("P-066", "Boa Hancock"),
                        ("P-110", "Monkey D. Luffy")]:
            rec = api.lookup(category="one_piece_tcg", product_id=pid)
            self.assertEqual(rec["specs"].get("character_name"), ch, pid)


class TestOpPromoSetBackfill(unittest.TestCase):
    def test_op_promo_event_sets_resolve(self):
        # OP06-118_p4 は 2026-07-30 revert 済 (§2 revert response 参照)。
        # 箱名 '2nd ANNIVERSARY SET' から一意 eBay facet が決まらないため mapping 削除。
        expect = {
            "OP01-001_p1": "Promo Cards", "OP01-017_p2": "Promo Cards",
            "OP03-044_p2": "Promo Cards", "OP12-031_p2": "Promo Cards",
            "ST01-006_p1": "Promo Cards", "ST01-013_p3": "Promo Cards",
        }
        for pid, ebay in expect.items():
            rec = api.lookup(category="one_piece_tcg", product_id=pid)
            self.assertEqual(rec["set_name"], ebay, pid)


class TestAnniversarySetPromoCardsGuard(unittest.TestCase):
    """2026-08-11 Advisor GO で 2nd ANNIVERSARY SET → Promo Cards に変更.

    経緯:
      - 2026-07-30 revert: '2nd ANNIVERSARY SET' の mapping を削除 (箱名から一意 facet
        決まらず 500 Years 誤 merge の実害があったため)。
      - 2026-08-11 GO (op03_001_p2_set_name_ebay_empty_response.md): 全 promo/event
        118 種を Promo Cards バケツで一括登録。'2nd ANNIVERSARY SET' もその中に含まれる。
        Advisor は「event 記念品は Promo Cards 集約が既存 convention」に基づき承認。

    本テストは新方針を固定する:
      - '2nd ANNIVERSARY SET' → 'Promo Cards' に mapping されている
      - OP06-118_p4 の set_name は依然として '500 Years in the Future' ではない
        (誤 merge 防止 = 元 revert の主目的は今も守られる)。"""

    def test_to_ebay_value_returns_promo_cards(self):
        v = api.to_ebay_value("one_piece_tcg", "set", "2nd ANNIVERSARY SET")
        self.assertEqual(v, "Promo Cards")

    def test_op06_118_p4_not_resolved_to_500_years(self):
        # 元 revert の主目的 (500 Years への誤 merge 防止) は今も守る:
        # OP06-118_p4 の set_name_official が '2nd ANNIVERSARY SET' なら
        # Promo Cards に解決し、500 Years にはならない。
        rec = api.lookup(category="one_piece_tcg", product_id="OP06-118_p4")
        self.assertIsNotNone(rec, "OP06-118_p4 が DB に無い")
        self.assertNotEqual(
            rec["set_name"], "500 Years in the Future",
            "revert 済のはずが '500 Years in the Future' に解決している",
        )


if __name__ == "__main__":
    unittest.main()
