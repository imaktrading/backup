"""variant_meta adapter test (= Pokemon variant Phase A.1).

依頼: 2026-05-27_catalog_variant_meta_phase_a_implementation.md
"""
from __future__ import annotations
import sys
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

from integrations import variant_meta  # noqa: E402
import api  # noqa: E402


class TestExtractVariantAlias(unittest.TestCase):
    """PSA Subject 表記揺れ → 正規 variant_code."""

    def test_alternate_art_full(self):
        self.assertEqual(variant_meta.extract_variant_alias("ALTERNATE ART"), "AR")
        self.assertEqual(variant_meta.extract_variant_alias("ALTERNATE ART CHARIZARD"), "AR")

    def test_alt_art_short(self):
        self.assertEqual(variant_meta.extract_variant_alias("ALT ART"), "AR")
        self.assertEqual(variant_meta.extract_variant_alias("ALT ART PIKACHU"), "AR")

    def test_special_art_rare(self):
        self.assertEqual(variant_meta.extract_variant_alias("SPECIAL ART RARE"), "SAR")
        self.assertEqual(variant_meta.extract_variant_alias("SPECIAL ART"), "SAR")
        self.assertEqual(variant_meta.extract_variant_alias("SAR EEVEE"), "SAR")

    def test_secret_rare(self):
        self.assertEqual(variant_meta.extract_variant_alias("SECRET RARE"), "SR")
        self.assertEqual(variant_meta.extract_variant_alias("SUPER RARE"), "SR")

    def test_hyper_ultra_rare(self):
        self.assertEqual(variant_meta.extract_variant_alias("HYPER RARE"), "HR")
        self.assertEqual(variant_meta.extract_variant_alias("ULTRA RARE"), "UR")

    def test_full_art(self):
        self.assertEqual(variant_meta.extract_variant_alias("FULL ART"), "FA")
        self.assertEqual(variant_meta.extract_variant_alias("FULL ART GIRATINA"), "FA")

    def test_promo_jumbo(self):
        self.assertEqual(variant_meta.extract_variant_alias("PROMO PIKACHU"), "Promo")
        self.assertEqual(variant_meta.extract_variant_alias("JUMBO LATIOS"), "Jumbo")

    def test_master(self):
        self.assertEqual(variant_meta.extract_variant_alias("MASTER"), "MA")

    def test_word_boundary_code(self):
        # 直接 code が subject に含まれる場合も拾う
        self.assertEqual(variant_meta.extract_variant_alias("CHARIZARD UR PROMO"), "UR")

    def test_no_match_returns_none(self):
        self.assertIsNone(variant_meta.extract_variant_alias("(no variant marker)"))
        self.assertIsNone(variant_meta.extract_variant_alias(""))
        self.assertIsNone(variant_meta.extract_variant_alias(None))

    def test_no_false_match_area(self):
        # 'AREA' は 'AR' を含むが variant_code じゃない (word boundary で区別)
        # ただし 'AR AREA' のように直接 code がある場合は拾う
        # 単純な 'PLAY AREA' は None 期待
        self.assertIsNone(variant_meta.extract_variant_alias("PLAY AREA"))


class TestGetVariantMetaFailClosed(unittest.TestCase):
    """fail-closed 動作 (= 未登録 / 不正 入力 → None)."""

    def test_empty_args(self):
        self.assertIsNone(variant_meta.get_variant_meta("", ""))
        self.assertIsNone(variant_meta.get_variant_meta("X", ""))
        self.assertIsNone(variant_meta.get_variant_meta("", "AR"))

    def test_unknown_product_id(self):
        self.assertIsNone(
            variant_meta.get_variant_meta("INVALID-NONEXISTENT-PID", "AR")
        )

    def test_unknown_variant_code(self):
        # 既存 catalog の任意 1 件で 'XX' (= 未登録 variant_code) → None
        conn = api._connect()
        try:
            row = conn.execute(
                "SELECT product_id FROM products WHERE category='pokemon_tcg' LIMIT 1"
            ).fetchone()
        finally:
            conn.close()
        if row:
            self.assertIsNone(
                variant_meta.get_variant_meta(row["product_id"], "XX")
            )


class TestGetVariantMetaIntegration(unittest.TestCase):
    """variants JSON 投入済 entry で取得確認 (= POC 投入 sample に依存)."""

    @classmethod
    def setUpClass(cls):
        # variants 投入済 entry を探す
        conn = api._connect()
        try:
            row = conn.execute(
                "SELECT product_id, variants FROM products "
                "WHERE category='pokemon_tcg' AND variants IS NOT NULL "
                "LIMIT 1"
            ).fetchone()
        finally:
            conn.close()
        if not row:
            raise unittest.SkipTest("variants 投入済 entry なし = test skip")
        cls.pid = row["product_id"]
        import json as _json
        cls.variants = _json.loads(row["variants"])
        cls.variant_code = next(iter(cls.variants.keys()))

    def test_lookup_returns_variants(self):
        rec = api.lookup("pokemon_tcg", self.pid)
        self.assertIsNotNone(rec)
        self.assertIsNotNone(rec.get("variants"))

    def test_meta_required_fields(self):
        meta = variant_meta.get_variant_meta(self.pid, self.variant_code)
        self.assertIsNotNone(meta)
        for k in ("features", "finish", "rarity_ebay", "title_token"):
            self.assertIn(k, meta)


if __name__ == "__main__":
    unittest.main()
