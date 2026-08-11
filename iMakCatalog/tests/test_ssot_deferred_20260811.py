"""SSOT deferred 反映 (2026-08-11 Advisor GO) の回帰テスト.

依頼: iMak_data/catalog/requests/2026-08-11_tcg_ssot_apply_result_and_deferred_response.md
  §1 表記規約22セット → 長形 (人が読める非-code 形)
  §4 SM4p 121件 (SM4p-* 120 + SM-P-145 1) → canonical `Sm4+: GX Battle Boost`
      + b_layer_status を unverified → verified_auto

このテストが守る不変条件:
  A) 22セットの現行 set_name_ebay が長形 (em-dash / code 形 でない)
  B) SM4p+SM-P-145 の 121行が canonical `Sm4+: GX Battle Boost`
  C) blanked_by_ultra_prism_mismap_20260731 の残りが 206 (327 - 121)
  D) SM4p の b_layer_status が verified_auto
"""
from __future__ import annotations
import json
import sqlite3
import sys
import unittest
from collections import Counter
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO.parent))
sys.path.insert(0, str(_REPO))
import api  # type: ignore  # noqa: E402


# §1 長形適用の期待値 (set_name_official → expected set_name_ebay).
# 4 群 (Sword & Shield - X / Scarlet & Violet - X) は master に regular-dash 版が在り、
# 残り 11 群は master に bare 版のみ (Astral Radiance / Fusion Strike 等) が在る。
LONGFORM_EXPECTED = {
    "拡張パック「ロストアビス」":         "Sword & Shield - Lost Origin",
    "拡張パック「漆黒のガイスト」":        "Sword & Shield - Chilling Reign",
    "拡張パック「白銀のランス」":         "Sword & Shield - Chilling Reign",
    "拡張パック「一撃マスター」":         "Sword & Shield - Battle Styles",
    "拡張パック「連撃マスター」":         "Sword & Shield - Battle Styles",
    "強化拡張パック「双璧のファイター」":    "Sword & Shield - Battle Styles",
    "拡張パック「パラダイムトリガー」":     "Sword & Shield - Silver Tempest",
    "拡張パック「黒炎の支配者」":         "Scarlet & Violet - Obsidian Flames",
    "拡張パック「スペースジャグラー」":     "Astral Radiance",
    "拡張パック「タイムゲイザー」":        "Astral Radiance",
    "拡張パック「バトルパートナーズ」":     "Journey Together",
    "拡張パック「フュージョンアーツ」":     "Fusion Strike",
    "拡張パック「ムゲンゾーン」":         "Darkness Ablaze",
    "拡張パック「仰天のボルテッカー」":     "Vivid Voltage",
    "拡張パック「反逆クラッシュ」":        "Rebel Clash",
    "拡張パック「摩天パーフェクト」":       "Evolving Skies",
    "強化拡張パック「Pokémon GO」":     "Pokémon GO",
    "強化拡張パック「ひかる伝説」":        "Shining Legends",
    "拡張パック「ひかる伝説」":          "Shining Legends",
}
LONGFORM_TOTAL_ROWS = 1814     # 実測値 (19 (set_official, se) pairs 合計)


class TestLongform22Sets(unittest.TestCase):
    """§1: 22セット (現行 15群 populated) が長形になっている."""

    def _rows_by_official(self, set_official: str):
        con = sqlite3.connect(str(api._DB_PATH))
        try:
            return con.execute(
                "SELECT product_id, json_extract(specs,'$.set_name_ebay') se "
                "FROM products WHERE category='pokemon_tcg' AND set_name_official=?",
                (set_official,)).fetchall()
        finally:
            con.close()

    def test_each_official_maps_to_expected_longform(self):
        for set_official, expected in LONGFORM_EXPECTED.items():
            rows = self._rows_by_official(set_official)
            self.assertGreater(len(rows), 0, f"{set_official}: 0行")
            values = Counter(r[1] for r in rows)
            self.assertEqual(
                dict(values), {expected: len(rows)},
                f"{set_official}: 期待 {expected!r} 単独。実測 {dict(values)}")

    def test_total_longform_row_count(self):
        """19 (set_official, se) pairs の合計行数 = 1814 (実測 baseline)."""
        con = sqlite3.connect(str(api._DB_PATH))
        try:
            n = 0
            for set_official in LONGFORM_EXPECTED:
                n += con.execute(
                    "SELECT count(*) FROM products WHERE category='pokemon_tcg' "
                    "AND set_name_official=?", (set_official,)).fetchone()[0]
        finally:
            con.close()
        self.assertEqual(n, LONGFORM_TOTAL_ROWS)

    def test_no_emdash_pokemon_rows_in_dual_scope(self):
        """22 dual 群の tail に該当する em-dash 形が pokemon_tcg に残っていない.

        現在の DB は em-dash 形 (`Sword & Shield—X`) を絶滅させ、
        `Sword & Shield - X` (regular dash) か bare (`Astral Radiance`) 形のみが残る."""
        emdash_targets = [
            "Sword & Shield—Astral Radiance", "Sword & Shield—Lost Origin",
            "Sword & Shield—Chilling Reign", "Sword & Shield—Battle Styles",
            "Sword & Shield—Silver Tempest", "Sword & Shield—Darkness Ablaze",
            "Sword & Shield—Fusion Strike",  "Sword & Shield—Vivid Voltage",
            "Sword & Shield—Rebel Clash",    "Sword & Shield—Evolving Skies",
            "Sword & Shield—Pokémon GO",    "Sun & Moon—Shining Legends",
            "Scarlet & Violet—Obsidian Flames",
            "Scarlet & Violet—Journey Together",
        ]
        con = sqlite3.connect(str(api._DB_PATH))
        try:
            for name in emdash_targets:
                n = con.execute(
                    "SELECT count(*) FROM products WHERE category='pokemon_tcg' "
                    "AND json_extract(specs,'$.set_name_ebay')=?", (name,)).fetchone()[0]
                self.assertEqual(n, 0, f"em-dash {name!r} が {n} 行残っている")
        finally:
            con.close()


class TestSm4pCanonicalPopulated(unittest.TestCase):
    """§4: SM4p+SM-P-145 の 121行が canonical `Sm4+: GX Battle Boost`."""

    SM4P_CANON = "Sm4+: GX Battle Boost"

    def _sm4p_rows(self):
        con = sqlite3.connect(str(api._DB_PATH))
        try:
            return con.execute(
                "SELECT product_id, json_extract(specs,'$.set_name_ebay') se, "
                "       json_extract(specs,'$.set_name_ebay_source') src "
                "FROM products WHERE category='pokemon_tcg' "
                "AND (product_id LIKE 'SM4p-%' OR product_id='SM-P-145')").fetchall()
        finally:
            con.close()

    def test_121_rows_have_canonical(self):
        rows = self._sm4p_rows()
        self.assertEqual(len(rows), 121, f"SM4p+SM-P-145: 121行 期待, 実測 {len(rows)}")
        vals = Counter(r[1] for r in rows)
        self.assertEqual(dict(vals), {self.SM4P_CANON: 121},
                         f"set_name_ebay 分布不一致: {dict(vals)}")

    def test_sm_p_145_included(self):
        """SM-P-145 が空欄で取り残されていない (同 set_official の1件孤児化を防止)."""
        rec = api.lookup(category="pokemon_tcg", product_id="SM-P-145")
        self.assertIsNotNone(rec)
        self.assertEqual(rec["specs"].get("set_name_ebay"), self.SM4P_CANON)

    def test_blanked_206_after_sm4p_reclaim(self):
        """§4 の副作用: 327 blanked - 121 SM4p = 206 が残 blank."""
        con = sqlite3.connect(str(api._DB_PATH))
        try:
            n = con.execute(
                "SELECT count(*) FROM products WHERE "
                "json_extract(specs,'$.set_name_ebay_source')="
                "'blanked_by_ultra_prism_mismap_20260731'").fetchone()[0]
        finally:
            con.close()
        self.assertEqual(n, 206)

    def test_sm4p_b_layer_status_verified(self):
        """SM4p+SM-P-145 の b_layer_status が verified_auto (blanking 時の unverified から回復)."""
        con = sqlite3.connect(str(api._DB_PATH))
        try:
            rows = con.execute(
                "SELECT b.status FROM b_layer_status b "
                "JOIN products p ON p.id=b.product_id_ref "
                "WHERE b.field='set_name_ebay' AND p.category='pokemon_tcg' "
                "AND (p.product_id LIKE 'SM4p-%' OR p.product_id='SM-P-145')").fetchall()
        finally:
            con.close()
        self.assertEqual(len(rows), 121)
        by_status = Counter(r[0] for r in rows)
        self.assertEqual(dict(by_status), {"verified_auto": 121},
                         f"b_layer_status 分布不一致: {dict(by_status)}")


if __name__ == "__main__":
    unittest.main()
