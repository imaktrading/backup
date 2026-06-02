"""Yu-Gi-Oh! TCG scraper + catalog 整合性 test."""
from __future__ import annotations
import json, sqlite3, sys, unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))
sys.path.insert(0, str(_REPO / "scrapers"))

from scrapers import yugioh_tcg  # noqa
import api  # noqa


class TestCardToRecord(unittest.TestCase):
    """API card dict → catalog record 変換."""

    def test_basic_ja_response(self):
        # language=ja API response sample
        api_card = {
            "id": 89631139,
            "name": "青眼の白龍",
            "name_en": "Blue-Eyes White Dragon",
            "type": "Normal Monster",
            "atk": 3000, "def": 2500, "level": 8,
            "attribute": "LIGHT",
            "archetype": "Blue-Eyes",
            "card_sets": [{"set_name": "Legend of Blue Eyes", "set_code": "LOB-001",
                            "set_rarity": "Ultra Rare", "set_rarity_code": "(UR)"}],
            "card_images": [{"id": 89631139, "image_url": "https://images.ygoprodeck.com/images/cards/89631139.jpg"}],
            "card_prices": [{"cardmarket_price": "1.50"}],
            "ygoprodeck_url": "https://ygoprodeck.com/card/blue-eyes-white-dragon-7485",
        }
        rec = yugioh_tcg.card_to_record(api_card)
        self.assertEqual(rec["product_id"], "89631139")
        self.assertEqual(rec["name_jp"], "青眼の白龍")
        self.assertEqual(rec["name_en"], "Blue-Eyes White Dragon")
        self.assertEqual(rec["name"], "青眼の白龍")
        self.assertIn("Legend of Blue Eyes", rec["set_name"])

    def test_missing_name_en_fallback(self):
        api_card = {
            "id": 12345,
            "name": "Test Card EN Only",  # ASCII alpha 含む = en と判定
            "type": "Spell Card",
            "race": "Continuous",
            "card_sets": [], "card_images": [], "card_prices": [],
        }
        rec = yugioh_tcg.card_to_record(api_card)
        self.assertEqual(rec["name_en"], "Test Card EN Only")
        self.assertIsNone(rec["name_jp"])

    def test_no_id_returns_none(self):
        rec = yugioh_tcg.card_to_record({})
        self.assertIsNone(rec)


class TestBuildSpecs(unittest.TestCase):
    def test_monster_specs(self):
        s = yugioh_tcg.build_specs({
            "type": "Normal Monster", "atk": 3000, "def": 2500, "level": 8,
            "attribute": "LIGHT", "archetype": "Blue-Eyes",
            "card_sets": [{"set_name": "LOB", "set_code": "LOB-001",
                            "set_rarity": "Ultra Rare"}],
        })
        self.assertEqual(s["atk"], 3000)
        self.assertEqual(s["level"], 8)
        self.assertEqual(s["primary_set_name"], "LOB")
        self.assertEqual(s["set_count"], 1)


class TestCatalogIntegrity(unittest.TestCase):
    """catalog 内 yugioh_tcg entry の必須 field 保証."""

    def test_all_have_name(self):
        conn = sqlite3.connect(str(api._DB_PATH))
        bad = []
        for pid, name in conn.execute(
            "SELECT product_id, name FROM products WHERE category='yugioh_tcg'"
        ).fetchall():
            if not name:
                bad.append(pid)
        conn.close()
        if bad:
            self.fail(f"yugioh_tcg entry without name: {len(bad)} 件 (sample: {bad[:5]})")

    def test_product_id_is_konami_id(self):
        """product_id は Konami 公式 ID (= numeric string) or variant 形式 `{passcode}_{set_code}`.

        2026-05-30 Phase G FULL expansion で variant 別 entry (= `{passcode}_{set_code}`、
        例 '10000000_BP01-EN021') を追加投入。 base entry は依然 numeric のみ。
        """
        import re
        conn = sqlite3.connect(str(api._DB_PATH))
        bad = []
        VARIANT_RE = re.compile(r"^\d+_[\w\-]+$")
        for (pid,) in conn.execute(
            "SELECT product_id FROM products WHERE category='yugioh_tcg' LIMIT 100"
        ).fetchall():
            if pid.isdigit():
                continue
            if VARIANT_RE.match(pid):
                continue  # variant entry OK
            bad.append(pid)
        conn.close()
        if bad:
            self.fail(f"non-numeric and non-variant product_id: {bad[:5]}")


class TestLookupYugioh(unittest.TestCase):
    """lookup_yugioh adapter (PSA subject → catalog Konami ID)."""

    @classmethod
    def setUpClass(cls):
        from integrations import psa_to_csv as cat_psa  # noqa
        cls.cat_psa = cat_psa

    def test_blue_eyes_white_dragon(self):
        r = self.cat_psa.lookup_yugioh(
            brand="YU-GI-OH! JAPANESE",
            card_number="001",
            subject="BLUE-EYES WHITE DRAGON",
            verbose=False,
        )
        self.assertIsNotNone(r)
        self.assertEqual(r["product_id"], "89631139")

    def test_dark_magician(self):
        r = self.cat_psa.lookup_yugioh(
            brand="YU-GI-OH! JAPANESE",
            card_number="001",
            subject="DARK MAGICIAN",
            verbose=False,
        )
        self.assertIsNotNone(r)
        self.assertEqual(r["product_id"], "46986414")

    def test_exodia_forbidden_one(self):
        """stopword 'THE' を含む subject でも 完全 token set 一致できる."""
        r = self.cat_psa.lookup_yugioh(
            brand="YU-GI-OH! JAPANESE",
            card_number="001",
            subject="EXODIA THE FORBIDDEN ONE",
            verbose=False,
        )
        self.assertIsNotNone(r)
        self.assertEqual(r["product_id"], "33396948")

    def test_derivative_not_matched(self):
        """派生カード (Malefic / Alternative) は subject に keyword 無いので
        完全 token set 一致しない → base card のみ採用される.
        ここでは subject 'BLUE-EYES WHITE DRAGON' → 'Malefic Blue-Eyes White
        Dragon' (= subject に MALEFIC 無し) を選ばないことを確認."""
        r = self.cat_psa.lookup_yugioh(
            brand="YU-GI-OH! JAPANESE",
            card_number="001",
            subject="BLUE-EYES WHITE DRAGON",
            verbose=False,
        )
        self.assertIsNotNone(r)
        self.assertNotIn("Malefic", r["name_en"])
        self.assertNotIn("Alternative", r["name_en"])

    def test_unknown_card_fail_closed(self):
        """未登録 card → None (= missing_models.csv 通知 path に流れる)."""
        r = self.cat_psa.lookup_yugioh(
            brand="YU-GI-OH! JAPANESE FAKE",
            card_number="XXX-001",
            subject="FAKE CARD XYZ NONEXISTENT",
            verbose=False,
        )
        self.assertIsNone(r)

    def test_empty_subject_skips(self):
        """subject 空 → fuzzy match 不可で None."""
        r = self.cat_psa.lookup_yugioh(
            brand="YU-GI-OH! JAPANESE",
            card_number="001",
            subject="",
            verbose=False,
        )
        self.assertIsNone(r)


if __name__ == "__main__":
    unittest.main()
