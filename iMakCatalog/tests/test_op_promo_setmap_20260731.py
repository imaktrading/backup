"""OP promo set_name_ebay backfill 回帰テスト (Advisor GO 2026-07-31).

対象:
  - iMak_data/catalog/requests/2026-07-30_audit_catalog_fix_tcg_response.md ①
    set_name_official='プロモーションカードセット' 13件 → set_name_ebay='Promo Cards'
  - iMak_data/catalog/requests/2026-07-30_pdca_catalog_queue_tcg_response.md A-1
    set_name_official='始めようキャンペーン プロモーションパック' 14件 → set_name_ebay='Promo Cards'

「filter_map yaml が誤って消えた/上書きされた」「specs 再計算で fail_closed に落ちた」
の再発を検出する fail-closed 回帰。

追加: prune_missing_models.is_out_of_scope の denylist 動作 (B群3行永久除外)。
"""
from __future__ import annotations
import json
import sqlite3
import sys
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO.parent))
sys.path.insert(0, str(_REPO))

import api  # noqa: E402
import prune_missing_models as prune  # noqa: E402


CAT = "one_piece_tcg"
SET_PROMO_CARD_SET = "プロモーションカードセット"
SET_LETS_START = "始めようキャンペーン プロモーションパック"


class TestFilterMapPromoBackfill(unittest.TestCase):
    """filter_map (DB) の 2 エントリが Promo Cards にマップされていること."""

    def test_promotion_card_set_maps_to_promo_cards(self):
        # audit_catalog_fix_tcg_response.md ①
        self.assertEqual(
            api.to_ebay_value(CAT, "set", SET_PROMO_CARD_SET), "Promo Cards"
        )

    def test_lets_start_campaign_maps_to_promo_cards(self):
        # pdca_catalog_queue_tcg_response.md A-1 (PERONA 4日居座りの真因)
        self.assertEqual(
            api.to_ebay_value(CAT, "set", SET_LETS_START), "Promo Cards"
        )

    def test_derive_set_name_ebay_promotion_card_set(self):
        """derive_set_name_ebay 経由 (実 scraper/migration 経路) でも Promo Cards."""
        v = api.derive_set_name_ebay(CAT, SET_PROMO_CARD_SET, "OP02-059_p2")
        self.assertEqual(v, "Promo Cards")

    def test_derive_set_name_ebay_lets_start(self):
        v = api.derive_set_name_ebay(CAT, SET_LETS_START, "OP01-077_p5")
        self.assertEqual(v, "Promo Cards")

    def test_derive_set_official_beats_prefix_lookup(self):
        """set_official 完全一致が [CODE]/prefix より優先されること
        (OP07-021_p2 は prefix=OP07='500 Years in the Future' に降格してはならない)."""
        v = api.derive_set_name_ebay(CAT, SET_LETS_START, "OP07-021_p2")
        self.assertEqual(v, "Promo Cards")
        self.assertNotEqual(v, "500 Years in the Future")


class TestProductsSpecsBackfilled(unittest.TestCase):
    """DB 上の 27 商品 (13+14) が全て set_name_ebay='Promo Cards' で埋まっていること."""

    def _count_by_specs(self, set_official: str):
        con = sqlite3.connect(str(api._DB_PATH))
        try:
            rows = con.execute(
                "SELECT specs FROM products WHERE category=? AND set_name_official=?",
                (CAT, set_official),
            ).fetchall()
        finally:
            con.close()
        total = len(rows)
        promo = 0
        fail_closed = 0
        for (specs_json,) in rows:
            s = json.loads(specs_json) if specs_json else {}
            if s.get("set_name_ebay") == "Promo Cards":
                promo += 1
            if s.get("set_name_ebay_source") == "fail_closed_no_map":
                fail_closed += 1
        return total, promo, fail_closed

    def test_promotion_card_set_13_rows_all_filled(self):
        total, promo, fc = self._count_by_specs(SET_PROMO_CARD_SET)
        self.assertEqual(total, 13, "set 内 row 数が 13 から変動")
        self.assertEqual(promo, 13, "全 13 件が Promo Cards になっていない")
        self.assertEqual(fc, 0, "fail_closed_no_map が残っている")

    def test_lets_start_14_rows_all_filled(self):
        total, promo, fc = self._count_by_specs(SET_LETS_START)
        self.assertEqual(total, 14, "set 内 row 数が 14 から変動")
        self.assertEqual(promo, 14, "全 14 件が Promo Cards になっていない")
        self.assertEqual(fc, 0, "fail_closed_no_map が残っている")

    def test_api_lookup_returns_promo_cards_for_key_products(self):
        """代表 product_id 経由 (listing 経路と同じ) で set_name='Promo Cards'."""
        # response letter 掲載の代表 4件
        for pid in ("OP02-059_p2", "OP01-077_p4", "OP01-077_p5", "OP07-021_p2"):
            rec = api.lookup(category=CAT, product_id=pid)
            self.assertIsNotNone(rec, f"{pid} が DB に無い")
            self.assertEqual(rec["set_name"], "Promo Cards", pid)


class TestOutOfScopeDenylist(unittest.TestCase):
    """prune_missing_models.is_out_of_scope の B群3件 永久除外."""

    def test_op_championship_2023_cert1_out_of_scope(self):
        model = ("cert153574704 ONE PIECE JAPANESE PROMOS "
                 "[PORTGAS D. ACE CHAMPIONSHIP SET 2023] #001 (auto)")
        reason = prune.is_out_of_scope(model)
        self.assertIsNotNone(reason)
        self.assertIn("championship", reason.lower())

    def test_op_championship_2023_cert2_out_of_scope(self):
        model = ("cert153574705 ONE PIECE JAPANESE PROMOS "
                 "[PORTGAS D. ACE CHAMPIONSHIP SET 2023] #001 (auto)")
        self.assertIsNotNone(prune.is_out_of_scope(model))

    def test_pokemon_neo_heracross_out_of_scope(self):
        model = "cert157799487 POKEMON JAPANESE NEO [HERACROSS-HOLO] #214 (auto)"
        reason = prune.is_out_of_scope(model)
        self.assertIsNotNone(reason)
        self.assertIn("neo", reason.lower())

    def test_perona_a1_is_not_denylisted(self):
        """A-1 の PERONA (cert153420191) は denylist に入れてはいけない
        (対象外ではなく解決済——p4/p5 の HQ 判定を待つ間、resolver 経路で扱う)."""
        model = ("cert153420191 ONE PIECE JAPANESE LET'S START CAMPAIGN "
                 "PROMOTION PACK [PERONA LET'S START CP PR PCK-ALT ART] #077 (auto)")
        self.assertIsNone(prune.is_out_of_scope(model))

    def test_non_cert_model_returns_none(self):
        self.assertIsNone(prune.is_out_of_scope("POKEMON ASIA 25TH ANNIVERSARY PROMO-005"))
        self.assertIsNone(prune.is_out_of_scope(""))
        self.assertIsNone(prune.is_out_of_scope(None))  # type: ignore[arg-type]

    def test_extract_cert(self):
        self.assertEqual(prune._extract_cert("cert12345 blah"), "cert12345")
        self.assertEqual(prune._extract_cert("cert157799487 POKEMON"), "cert157799487")
        self.assertIsNone(prune._extract_cert("POKEMON ASIA PROMO-005"))


if __name__ == "__main__":
    unittest.main()
