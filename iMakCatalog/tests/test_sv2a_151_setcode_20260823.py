"""ポケモンカード151 (SV2a) の Set 値を固定する (2026-08-23).

依頼: requests/2026-08-19_set_name_151_form.md
回答: requests/2026-08-19_set_name_151_form_response.md ([IMPLEMENT-GO])

## 何が起きていたか

products の 210行には正しい `Sv2a: Pokemon Card 151` が焼いてあったのに、
変換表 (`ebay_filter_map/pokemon.yaml` の set_code SV2a) だけが
**`Pokemon 151` (eBay master に存在しない値) のまま REVIEW で残っていた**。

そのため derive だけが古い値を返し、監査 §6 の canonical ズレに 210行が乗り続けていた
(1,108 → 修正後 898 = ちょうど 210 減)。
`restamp` の格下げ禁止ガードが効いていたので products は塗り潰されずに済んでいたが、
ガードを1つ外せば 210行が master に無い値へ落ちる状態だった。

## ここで固定すること

1. 変換表の値が eBay master (Pokémon TCG) に **verbatim で在る**
2. 英語版 MEW の `Sv: Scarlet & Violet 151` を日本語版に当てない (ルール③ 禁止)
3. 焼いてある値と derive が一致する (§6 ズレを 0 に保つ)
"""
from __future__ import annotations

import json
import sqlite3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))

import api  # noqa: E402

MASTER = Path(r"C:\dev\iMak_data\catalog\_input\ebay_aspects_183454_latest.json")

JP_151_SET = "強化拡張パック「ポケモンカード151（イチゴーイチ）」"
CORRECT = "Sv2a: Pokemon Card 151"
EN_MEW = "Sv: Scarlet & Violet 151"   # 英語版 MEW = 別セット。当てたら誤出品
OLD_WRONG = "Pokemon 151"             # master に無い旧値 (REVIEW のまま残っていた)


def _ebay_pokemon_set_values() -> set:
    node = json.loads(MASTER.read_text(encoding="utf-8"))["aspects"]["Set"]
    return set(node["by_game"].get("Pokémon TCG") or [])


class TestSv2aFilterMap(unittest.TestCase):
    def test_set_code_maps_to_code_form(self):
        self.assertEqual(api.to_ebay_value("pokemon_tcg", "set_code", "SV2a"), CORRECT)

    def test_derive_matches_code_form(self):
        self.assertEqual(
            api.derive_set_name_ebay("pokemon_tcg", JP_151_SET, "SV2a-001"), CORRECT)

    def test_old_value_is_gone(self):
        """`Pokemon 151` は eBay master に無い。戻ったら即失敗させる."""
        self.assertNotEqual(api.to_ebay_value("pokemon_tcg", "set_code", "SV2a"), OLD_WRONG)


class TestValueIsVerbatimInEbayMaster(unittest.TestCase):
    def test_correct_value_exists_in_master(self):
        vals = _ebay_pokemon_set_values()
        self.assertIn(CORRECT, vals)

    def test_old_value_absent_from_master(self):
        """旧値が master に無いことが「①カタログが誤り」の根拠そのもの."""
        self.assertNotIn(OLD_WRONG, _ebay_pokemon_set_values())


class TestStoredRows(unittest.TestCase):
    def _rows(self):
        db = sqlite3.connect(api._DB_PATH, timeout=60)
        try:
            return db.execute(
                "SELECT product_id, json_extract(specs,'$.set_name_ebay') "
                "FROM products WHERE category='pokemon_tcg' AND set_name_official=?",
                (JP_151_SET,)).fetchall()
        finally:
            db.close()

    def test_all_151_rows_use_code_form(self):
        rows = self._rows()
        self.assertTrue(rows, "151 の行が1つも無い (set_name_official が変わった?)")
        for pid, val in rows:
            self.assertEqual(val, CORRECT, f"{pid} の set_name_ebay が {val!r}")

    def test_no_row_uses_english_mew_set(self):
        """ルール③: 日本語版カードに英語版セット名を当てない (例外は作らない)."""
        for pid, val in self._rows():
            self.assertNotEqual(val, EN_MEW, f"{pid} に英語版 MEW のセット名が入っている")

    def test_no_drift_for_151(self):
        """焼いてある値 == derive。§6 canonical ズレを 151 で 0 に保つ."""
        db = sqlite3.connect(api._DB_PATH, timeout=60)
        try:
            rows = db.execute(
                "SELECT product_id, json_extract(specs,'$.set_name_ebay') "
                "FROM products WHERE category='pokemon_tcg' AND set_name_official=?",
                (JP_151_SET,)).fetchall()
        finally:
            db.close()
        for pid, stored in rows:
            self.assertEqual(
                api.derive_set_name_ebay("pokemon_tcg", JP_151_SET, pid), stored,
                f"{pid} で derive と stored がズレている")


if __name__ == "__main__":
    unittest.main()
