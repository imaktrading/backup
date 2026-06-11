"""Pokemon set-code 0↔O 取り違え正規化 test (2026-06-11).

依頼: requests/2026-06-11_pokemon_0O_setcode_and_25th_promo_gap.md (HQ).
cert 131660897 Marnie's Morpeko: PSA brand「SV0M」(数字0) で catalog 実在の
`SVOM-020`(英字O) を拾えない事故の再発防止。ID 完全一致 lookup 専用なので fail-closed。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))
sys.path.insert(0, str(_REPO / "integrations"))

import psa_to_csv as pc  # type: ignore  # noqa: E402


class TestSetCodeVariants(unittest.TestCase):
    """_set_code_lookup_variants pure 関数."""

    def test_digit0_yields_letterO(self):
        v = pc._set_code_lookup_variants("SV0M")
        self.assertIn("SVOM", v)        # 数字0 → 英字O
        self.assertEqual(v[0], "SV0M")  # 元を最優先

    def test_letterO_yields_digit0(self):
        v = pc._set_code_lookup_variants("SVOM")
        self.assertIn("SV0M", v)        # 逆方向救済

    def test_no_0O_no_extra_variant(self):
        # 0/O を含まない通常 set-code は case 違いのみ (回帰防止)
        v = pc._set_code_lookup_variants("S8a")
        self.assertEqual(set(v), {"S8a", "S8A", "s8a"})

    def test_empty(self):
        self.assertEqual(pc._set_code_lookup_variants(""), [])


class TestLookupPokemon0O(unittest.TestCase):
    """実 catalog DB に対する 0/O 解決 (SVOM-020 が実在する前提)."""

    def test_sv0m_digit0_resolves_to_svom(self):
        # cert 131660897 の実ケース: PSA「SV0M」(数字0) → 公式「SVOM-020」(英字O)
        r = pc.lookup_pokemon(
            "POKEMON JAPANESE SV0M-EX STARTER SET MARNIE MORPEKO",
            "020", subject="", verbose=False)
        self.assertIsNotNone(r)
        self.assertEqual(r["set_code"], "SVOM")
        self.assertEqual(r["card_number"], "020")

    def test_nonexistent_number_fail_closed(self):
        # 0/O 正規化しても存在しない番号は None (推測しない)
        r = pc.lookup_pokemon(
            "POKEMON JAPANESE SV0M-EX STARTER SET", "999", subject="", verbose=False)
        self.assertIsNone(r)


if __name__ == "__main__":
    unittest.main()
