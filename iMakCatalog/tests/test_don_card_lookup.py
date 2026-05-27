"""DON カード lookup_don() integration test.

依頼: 2026-05-27_don_card_psa_subject_lookup.md

前提: catalog DB に DON カード 265 件投入済 (= migration 2026-05-27_don_cards_invest.py +
       psa_subject_hint 2026-05-27_don_psa_subject_hint.py 適用済).

test 戦略:
  - 既存 catalog DB を read-only で参照、 DB の事前状態に依存
  - 主要 set_code (OP15 / KUMAMON / STORAGE / PRB01 / EB04) を実機検証
  - fail-closed pattern (= 非 DON / 一意特定不能) も検証
"""
from __future__ import annotations
import sys
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

from integrations import psa_to_csv  # noqa: E402
import api  # noqa: E402


class TestLookupDonBasic(unittest.TestCase):
    """DON lookup の基本動作."""

    @classmethod
    def setUpClass(cls):
        # catalog DB に DON entries 投入済か確認
        n = 0
        conn = api._connect()
        try:
            n = conn.execute(
                "SELECT COUNT(*) FROM products WHERE category='one_piece_tcg' "
                "AND product_id LIKE 'DON-%'"
            ).fetchone()[0]
        finally:
            conn.close()
        if n == 0:
            raise unittest.SkipTest("DON entries 未投入 = test skip")
        cls.don_total = n

    def test_op15_alt_art_gold(self):
        """OP-15 DON Alt Art Gold → DON-OP15-002 (= variant 2)."""
        r = psa_to_csv.lookup_don(
            brand="ONE PIECE JAPANESE OP-15 ADVENTURE ON KAMIS ISLAND",
            subject="DON!! CARD ALTERNATE ART GOLD",
            verbose=False,
        )
        self.assertIsNotNone(r)
        self.assertEqual(r["product_id"], "DON-OP15-002")

    def test_non_don_card_returns_none(self):
        """subject に 'DON' なし → None (= 非 DON、 早期 return)."""
        r = psa_to_csv.lookup_don(
            brand="ONE PIECE JAPANESE OP08",
            subject="MONKEY D LUFFY",
            verbose=False,
        )
        self.assertIsNone(r)

    def test_kumamon_zoro(self):
        """KUMAMON RORONOA ZORO → DON-KUMAMON-* で Zoro variant 特定."""
        r = psa_to_csv.lookup_don(
            brand="ONE PIECE JAPANESE KUMAMON",
            subject="DON!! CARD RORONOA ZORO",
            verbose=False,
        )
        self.assertIsNotNone(r)
        self.assertTrue(r["product_id"].startswith("DON-KUMAMON-"))

    def test_storage_red(self):
        """STORAGE BOX RED → DON-STORAGE-001 (= RED variant)."""
        r = psa_to_csv.lookup_don(
            brand="ONE PIECE STORAGE BOX",
            subject="DON!! CARD STORAGE RED",
            verbose=False,
        )
        self.assertIsNotNone(r)
        self.assertEqual(r["product_id"], "DON-STORAGE-001")

    def test_prb01_position_match(self):
        """PRB-01 + subject に #042 → DON-PRB01-042 で position 番号特定."""
        r = psa_to_csv.lookup_don(
            brand="ONE PIECE JAPANESE PRB-01",
            subject="DON!! CARD #042",
            verbose=False,
        )
        self.assertIsNotNone(r)
        self.assertEqual(r["product_id"], "DON-PRB01-042")

    def test_op15_standard_ambiguous_fail_closed(self):
        """OP-15 + subject に variant keyword なし → None (= fail-closed)."""
        r = psa_to_csv.lookup_don(
            brand="ONE PIECE JAPANESE OP-15",
            subject="DON!! CARD",
            verbose=False,
        )
        self.assertIsNone(r)

    def test_eb04_egghead_alt(self):
        """EB-04 EGGHEAD CRISIS + ALTERNATE ART → DON-EB04-002."""
        r = psa_to_csv.lookup_don(
            brand="ONE PIECE JAPANESE EB-04 EGGHEAD CRISIS",
            subject="DON!! CARD ALTERNATE ART",
            verbose=False,
        )
        self.assertIsNotNone(r)
        self.assertEqual(r["product_id"], "DON-EB04-002")

    def test_empty_subject_returns_none(self):
        """subject 空 → None (= DON marker 検出不可)."""
        r = psa_to_csv.lookup_don(
            brand="ONE PIECE JAPANESE OP-15",
            subject="",
            verbose=False,
        )
        self.assertIsNone(r)


class TestLookupDonInternalKey(unittest.TestCase):
    """DON record の specs に 内部 KEY 注意書きが含まれることを検証."""

    def test_internal_key_note_present(self):
        """hit した record の specs に catalog_internal_key_note 含むこと."""
        r = psa_to_csv.lookup_don(
            brand="ONE PIECE JAPANESE OP-15 ADVENTURE",
            subject="DON!! CARD ALTERNATE ART GOLD",
            verbose=False,
        )
        if r is None:
            self.skipTest("DON entries 未投入")
        specs = r.get("specs") or {}
        # specs が string なら parse
        if isinstance(specs, str):
            import json
            specs = json.loads(specs)
        # psa_subject_hint と catalog_internal_key_note 両方あること
        self.assertIn("psa_subject_hint", specs)
        self.assertIn("catalog_internal_key_note", specs)
        # 内部 KEY 警告文に「公式 card_number 不在」 入ること
        self.assertIn("公式 card_number 不在", specs["catalog_internal_key_note"])


if __name__ == "__main__":
    unittest.main()
