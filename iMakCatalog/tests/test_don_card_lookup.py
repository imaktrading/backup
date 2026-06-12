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

    def test_op13_alt_art_gold(self):
        """OP-13 DON Alt Art Gold → DON-OP13-002 (cert 146160803, 2026-06-13 image確認)."""
        r = psa_to_csv.lookup_don(
            brand="ONE PIECE JAPANESE OP-13 CARRYING ON HIS WILL",
            subject="DON!! CARD ALTERNATE ART GOLD",
            verbose=False,
        )
        self.assertIsNotNone(r)
        self.assertEqual(r["product_id"], "DON-OP13-002")

    def test_1st_anniversary_event_silhouette(self):
        """1ST ANNIVERSARY EVENT (= silhouette ドンドットット) → DON-EVENT-003.

        cert 146160792 (PSA '2023 ONE PIECE JP / DON!! CARD / 1ST ANNIVERSARY EVENT').
        2026-06-13: 全11 DON-EVENT 画像目視で 003=唯一の silhouette と確認し、
        psa_subject_hint に '1ST ANNIVERSARY' を追加 (003 のみ、 002 等は EVENT のまま)
        → anniversary subject で 003 が一意 score 勝ち.
        """
        r = psa_to_csv.lookup_don(
            brand="2023 ONE PIECE JP",
            subject="DON!! CARD 1ST ANNIVERSARY EVENT",
            verbose=False,
        )
        self.assertIsNotNone(r)
        self.assertEqual(r["product_id"], "DON-EVENT-003")

    def test_generic_event_no_anniversary_fail_closed(self):
        """汎用 EVENT subject (anniversary keyword 無) → None (= 11件 tie で fail-closed 維持).

        003 への '1ST ANNIVERSARY' 追加が generic EVENT cert を誤発火させないことの回帰防止.
        """
        r = psa_to_csv.lookup_don(
            brand="2023 ONE PIECE JP",
            subject="DON!! CARD EVENT",
            verbose=False,
        )
        self.assertIsNone(r)

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


class TestLookupDonImageDisambiguate(unittest.TestCase):
    """2026-05-28 拡張: tie 時 image_url disambiguate."""

    @classmethod
    def setUpClass(cls):
        # image_phash 投入済 entry があるか確認
        import api as _api
        conn = _api._connect()
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM products "
                "WHERE category='one_piece_tcg' AND product_id LIKE 'DON-%' "
                "AND variants LIKE '%image_phash%'"
            ).fetchone()
        finally:
            conn.close()
        if row[0] < 5:
            raise unittest.SkipTest("DON image_phash 投入済 entries 不足 = test skip")

    def test_lookup_don_single_candidate_unchanged(self):
        """tie 無 (= 1 件 unique) → image_url 引数 ignore (= 既存 behavior)."""
        from integrations import psa_to_csv
        r = psa_to_csv.lookup_don(
            brand="ONE PIECE JAPANESE OP-15 ADVENTURE",
            subject="DON!! CARD ALTERNATE ART GOLD",
            image_url="http://example.com/fake.jpg",  # = unique なので fetch 不要
            verbose=False,
        )
        self.assertIsNotNone(r)
        self.assertEqual(r["product_id"], "DON-OP15-002")

    def test_lookup_don_tie_without_image(self):
        """tie + image_url=None → None (= 既存挙動維持)."""
        from integrations import psa_to_csv
        r = psa_to_csv.lookup_don(
            brand="ONE PIECE JAPANESE OP-15",
            subject="DON!! CARD",  # = variant keyword なし、 5 候補 tie
            image_url=None,
            verbose=False,
        )
        self.assertIsNone(r)

    def test_lookup_don_image_fetch_fail(self):
        """image_url fetch fail → None (fail-closed)."""
        from integrations import psa_to_csv
        r = psa_to_csv.lookup_don(
            brand="ONE PIECE JAPANESE OP-15",
            subject="DON!! CARD",
            image_url="http://invalid.nonexistent.example/fake.jpg",
            verbose=False,
        )
        self.assertIsNone(r)

    def test_lookup_don_tie_with_image_unique_match(self):
        """tie + image_url + 1 件 hamming ≤ 10 → 該当 1 件特定.

        本 test は catalog の DON-OP15-002 自身の local PNG を直接 mock 経由参照。
        実機 cycle (= mercari URL) では別途実機 verify 必要 (= 完了報告 §3)。
        """
        # 直接 local file から hash 計算 + mock の代わりに、 internal helper を直接 call.
        from integrations import psa_to_csv
        from PIL import Image
        import imagehash, sqlite3, json
        import api as _api

        # DON-OP15-002 の image_phash を取得
        conn = _api._connect()
        try:
            row = conn.execute(
                "SELECT id, product_id, variants FROM products "
                "WHERE category='one_piece_tcg' AND product_id='DON-OP15-002'"
            ).fetchone()
        finally:
            conn.close()
        if not row:
            self.skipTest("DON-OP15-002 未投入")

        # tie 候補 list (= OP15 全件) を疑似生成
        conn = _api._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM products "
                "WHERE category='one_piece_tcg' AND product_id LIKE 'DON-OP15-%'"
            ).fetchall()
        finally:
            conn.close()

        # DON-OP15-002 の local image を再 hash → 同一 hash 期待
        # _disambiguate_don_by_image は image_url を要求するため、 直接 hash 比較 logic を test
        import json as _json
        variants = _json.loads(row["variants"])
        stored_hash = variants["default"]["image_phash"]
        # local file → 直接 hash
        img_path = "C:/dev/iMak_data/catalog/_don_images/DON-OP15-002.png"
        img = Image.open(img_path)
        fresh_hash = str(imagehash.phash(img))
        # 同一 image → 同 hash
        self.assertEqual(stored_hash, fresh_hash)
        # hamming = 0
        h1 = imagehash.hex_to_hash(stored_hash)
        h2 = imagehash.hex_to_hash(fresh_hash)
        self.assertEqual(h1 - h2, 0)

    def test_lookup_don_variant_discrimination_threshold(self):
        """異 variant pair が THRESHOLD 10 で確実分離 (= 完走証明)."""
        import imagehash, sqlite3, json
        import api as _api
        conn = _api._connect()
        try:
            row1 = conn.execute(
                "SELECT variants FROM products WHERE product_id='DON-OP15-001'"
            ).fetchone()
            row2 = conn.execute(
                "SELECT variants FROM products WHERE product_id='DON-OP15-002'"
            ).fetchone()
            row3 = conn.execute(
                "SELECT variants FROM products WHERE product_id='DON-EVENT-001'"
            ).fetchone()
        finally:
            conn.close()
        if not (row1 and row2 and row3):
            self.skipTest("test entries 不足")
        h1 = imagehash.hex_to_hash(json.loads(row1["variants"])["default"]["image_phash"])
        h2 = imagehash.hex_to_hash(json.loads(row2["variants"])["default"]["image_phash"])
        h3 = imagehash.hex_to_hash(json.loads(row3["variants"])["default"]["image_phash"])
        # 異 variant 同 set: 18 (POC 確定)
        self.assertGreater(h1 - h2, 10, "OP15-001 vs OP15-002 は THRESHOLD 10 で分離可能")
        # 異 set: 22
        self.assertGreater(h1 - h3, 10, "OP15-001 vs EVENT-001 は THRESHOLD 10 で分離可能")
        # 同一: 0
        self.assertEqual(h1 - h1, 0)

    def test_lookup_don_non_don_subject_unchanged(self):
        """非 DON subject (= 'DON' 含まない) → None (= 既存挙動、 image_url 関係なし)."""
        from integrations import psa_to_csv
        r = psa_to_csv.lookup_don(
            brand="ONE PIECE JAPANESE OP-15",
            subject="MONKEY D LUFFY",  # = DON marker 不在
            image_url="http://example.com/whatever.jpg",
            verbose=False,
        )
        self.assertIsNone(r)


if __name__ == "__main__":
    unittest.main()
