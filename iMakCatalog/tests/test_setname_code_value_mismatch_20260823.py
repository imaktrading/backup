"""§0c 別セットの名前 (弾番号が付いていない形) の検知を固定する.

経緯: §0 は **eBay 値の頭に弾番号が付いている時しか**比べられない (`Sv4k:` 等)。
`Sun & Moon` / `Triumphant` / `Roaring Skies` のような英語版セット名は弾番号が無いので
§0 を素通りし、eBay の一覧に実在する値なので §0b も通る。2026-08-23 実測で
pokemon_tcg に 1,798行 (日本語版の刷りに英語版セット名) が残っていた。

§0c の条件は1つだけ:
    eBay master に **その商品の弾コードで始まる値が在る** のに、焼いてある値がそれでない

除外は1つだけ: 焼いてある値が **その弾自身の名前で始まっている** 時 (`S8a-P: …` は
S8a の別商品なので誤りではない)。★自由入力の登録簿は免罪符にしない — 値が在る弾に
登録があるなら、その登録自体が誤り (実測: `Mask of Change` / `Rocket Gang's Glory` /
`20th Anniversary` の3値が 356行を隠していた)。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))
sys.path.insert(0, str(_REPO / "tools"))

import set_name_integrity_audit as A  # type: ignore  # noqa: E402


class TestNamesOwnSetcode(unittest.TestCase):
    """除外条件そのもの (弾自身の名前で始まるか)."""

    def test_sub_product_of_same_set_is_exempt(self):
        # S8a-P (プロモカードパック) は S8a の別商品 = 誤りではない
        self.assertTrue(A.names_own_setcode(
            "S8a-P: Promo Card Pack 25th Anniversary Edition", "S8a"))
        self.assertTrue(A.names_own_setcode("S8a: 25th Anniversary Collection", "S8a"))

    def test_english_set_name_is_not_exempt(self):
        self.assertFalse(A.names_own_setcode("Noble Victories", "BW2"))
        self.assertFalse(A.names_own_setcode("Sun & Moon", "SM1S"))
        self.assertFalse(A.names_own_setcode("Triumphant", "L3"))

    def test_empty_setcode_never_exempts(self):
        self.assertFalse(A.names_own_setcode("Anything", ""))


class TestCodeValueMismatchDetection(unittest.TestCase):
    """実 DB に対して 0c が動くこと (件数は動くので、性質だけ固定する)."""

    @classmethod
    def setUpClass(cls):
        out = A.audit(["pokemon_tcg"])
        cls.mismatch = out[10]

    def test_returns_tuples_with_candidates(self):
        for pid, sc, e, cand in self.mismatch[:20]:
            self.assertTrue(pid and sc and e)
            self.assertTrue(cand, f"{pid}: 候補が空なら flag してはいけない")
            self.assertNotIn(e, cand, f"{pid}: 候補に在る値を flag している")

    def test_no_exempt_row_is_flagged(self):
        # 弾自身の名前で始まる値は 1 件も入っていないこと
        bad = [(pid, e) for pid, sc, e, _ in self.mismatch
               if A.names_own_setcode(e, sc)]
        self.assertEqual(bad, [], f"除外すべき行が flag されている: {bad[:5]}")

    def test_known_english_set_names_are_caught(self):
        vals = {e for _, _, e, _ in self.mismatch}
        # 直っていれば 0 件になる。その時は「捕まえる対象が無い」= skip
        if not vals:
            self.skipTest("0c は 0 件 (= 是正済)")
        self.assertTrue(
            vals & {"Sun & Moon", "Triumphant", "Noble Victories",
                    "Mask of Change", "20th Anniversary"},
            "英語版セット名が 1 つも捕まっていない = 条件が壊れている")


if __name__ == "__main__":
    unittest.main()
