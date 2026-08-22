"""SSOT deferred 反映 (2026-08-11 Advisor GO) の回帰テスト.

依頼: iMak_data/catalog/requests/2026-08-11_tcg_ssot_apply_result_and_deferred_response.md
  §1 表記規約22セット → **コード形** (2026-08-18 HQ 裁定で長形から変更)
  §4 SM4p 121件 (SM4p-* 120 + SM-P-145 1) → canonical `Sm4+: GX Battle Boost`
      + b_layer_status を unverified → verified_auto

このテストが守る不変条件:
  A) 22セットの現行 set_name_ebay が master verbatim の**コード形**
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


# §1 コード形適用の期待値 (set_name_official → expected set_name_ebay).
#
# ★2026-08-18 変更: 長形 → コード形。
#   本テストは元々 2026-08-11 の Advisor 暫定 GO (長形) を守っていたが、その暫定 GO 自身が
#   「どちらの表記に出品が多く集まっているかは測れていません (eBay 検索は 403)。
#     **後で分かれば戻せる範囲の判断です**」と明記していた。
#   HQ が 2026-08-18 に eBay 本番 API (cat 183454 / EBAY_US) で実測し、
#   長形が相手のときコード形が 7.5倍 (Lost Origin 171,639 vs 22,904 /
#   Obsidian Flames 176,034 vs 23,179)、素名が相手なら差 10% 以内 = 最悪でも引き分け。
#   → コード形で確定。回答書:
#      requests/2026-08-10_tcg_ssot_a4_result_and_one_decision_req_response.md [IMPLEMENT-GO]
#
# 値は eBay master (cat 183454 / 2,290値) の **verbatim**。組み立てない
# (`SV02:` は master に無く `Sv02:` が正)。1文字違うと eBay はエラーを返さず
# カテゴリ全件が返る = 絞り込めていないのに正常応答に見える。
# `Swsh12: Sword & Shield - Silver Tempest` のようにコード形自体がシリーズ名を含む値もそのまま。
CODEFORM_EXPECTED = {
    "拡張パック「ロストアビス」":         "S11: Lost Abyss",
    "拡張パック「漆黒のガイスト」":        "S6k: Jet-Black Spirit",
    "拡張パック「白銀のランス」":         "S6h: Silver Lance",
    "拡張パック「一撃マスター」":         "S5i: Single Strike Master",
    "拡張パック「連撃マスター」":         "S5r: Rapid Strike Master",
    "強化拡張パック「双璧のファイター」":    "S5a: Peerless Fighters",
    "拡張パック「パラダイムトリガー」":     "S12: Paradigm Trigger",
    "拡張パック「黒炎の支配者」":         "SV03: Obsidian Flames",
    "拡張パック「スペースジャグラー」":     "S10p: Space Juggler",
    "拡張パック「タイムゲイザー」":        "S10d: Time Gazer",
    # ★2026-08-22 是正: 英語版 SV09 の名前が入っていた (別セット)。
    #   日本語版の刷りには 'Sv9: Battle Partners' (eBay master に実在) が正しい。
    # 2026-08-23 ユーザー確定「シンプルが一番」: 日本語版セットは自分の値を使う。
    #   英語版セット名の流用 (08-18 の例外14セット) は廃止した。
    "拡張パック「バトルパートナーズ」":     "Sv9: Battle Partners",
    "拡張パック「フュージョンアーツ」":     "S8: Fusion Arts",
    "拡張パック「ムゲンゾーン」":         "S3: Infinity Zone",
    "拡張パック「仰天のボルテッカー」":     "S4: Amazing Volt Tackle",
    "拡張パック「反逆クラッシュ」":        "S2: Rebellion Crash",
    "拡張パック「摩天パーフェクト」":       "S7d: Skyscraping Perfection",
    "強化拡張パック「Pokémon GO」":     "S10b: Pokémon GO",
    "強化拡張パック「ひかる伝説」":        "Sm3+: Shining Legends",
    "拡張パック「ひかる伝説」":          "Sm3+: Shining Legends",
    # 2026-08-18 追加: HQ 実測表に在るが 08-11 の長形リストから漏れていた 1 群
    "ハイクラスパック「テラスタルフェスex」":  "Sv: Prismatic Evolutions",
}
CODEFORM_TOTAL_ROWS = 2051     # 実測値 (20 official 合計. 旧 19 official=1814 + テラスタルフェスex 237)


class TestCodeform22Sets(unittest.TestCase):
    """§1: 22セット (現行 20 official / 15 set) が master verbatim のコード形になっている."""

    def _rows_by_official(self, set_official: str):
        con = sqlite3.connect(str(api._DB_PATH))
        try:
            return con.execute(
                "SELECT product_id, json_extract(specs,'$.set_name_ebay') se "
                "FROM products WHERE category='pokemon_tcg' AND set_name_official=?",
                (set_official,)).fetchall()
        finally:
            con.close()

    def test_each_official_maps_to_expected_codeform(self):
        for set_official, expected in CODEFORM_EXPECTED.items():
            rows = self._rows_by_official(set_official)
            self.assertGreater(len(rows), 0, f"{set_official}: 0行")
            values = Counter(r[1] for r in rows)
            self.assertEqual(
                dict(values), {expected: len(rows)},
                f"{set_official}: 期待 {expected!r} 単独。実測 {dict(values)}")

    def test_total_codeform_row_count(self):
        """20 official の合計行数 = 2051 (実測 baseline)."""
        con = sqlite3.connect(str(api._DB_PATH))
        try:
            n = 0
            for set_official in CODEFORM_EXPECTED:
                n += con.execute(
                    "SELECT count(*) FROM products WHERE category='pokemon_tcg' "
                    "AND set_name_official=?", (set_official,)).fetchone()[0]
        finally:
            con.close()
        self.assertEqual(n, CODEFORM_TOTAL_ROWS)

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
        self.assertEqual(n, 0)

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
