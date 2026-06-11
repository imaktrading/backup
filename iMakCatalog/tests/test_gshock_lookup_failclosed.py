"""G-shock lookup_gshock fail-closed 規約 test (2026-06-11 dedupe 後).

依頼: requests/2026-06-11_gshock_bare_dedupe_round2_HQ_verdict.md (HQ 承認ルール).
保証する fail-closed 規約:
  - suffix 形入力 → suffix canonical に exact 解決
  - bare 形 + suffix twin 在り → "" (None) 返却 (1:N 曖昧、推測しない)
  - bare 形 + suffix twin 無し → bare-only canonical → 解決
  - 末尾 A は色コード (AJF=色A+JF)。GBX-100-2(色2) を GBX-100-2AJF(色2A) の twin と
    誤判定しないこと (= round-1 誤削除事故の再発防止).
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))
sys.path.insert(0, str(_REPO / "integrations"))

from integrations.gshock_lookup import (  # type: ignore  # noqa: E402
    lookup_gshock, _normalize_forms, _split_region, _has_region_twin,
)


class TestSplitRegion(unittest.TestCase):
    """_split_region: J 始まり region のみ剥がす. 末尾 A は色なので残す."""

    def test_jf_stripped(self):
        self.assertEqual(_split_region("DW-6900RCS-1JF"), ("DW-6900RCS-1", "JF"))

    def test_jr_stripped(self):
        self.assertEqual(_split_region("DW-6900SBY-2JR"), ("DW-6900SBY-2", "JR"))

    def test_ajf_keeps_color_A(self):
        # 末尾 A は色コード → region は JF、base は ...A を保持
        self.assertEqual(_split_region("GBX-100-2AJF"), ("GBX-100-2A", "JF"))

    def test_bare_no_region(self):
        self.assertEqual(_split_region("GA-2100-1A1"), ("GA-2100-1A1", None))

    def test_overseas_suffix_not_stripped(self):
        # 海外 suffix (E/V/ER 等) は region 扱いしない
        self.assertEqual(_split_region("DW-5600E-1"), ("DW-5600E-1", None))


class TestNormalizeForms(unittest.TestCase):
    def test_uppercase(self):
        self.assertIn("DW-6900RCS-1JF", _normalize_forms("dw-6900rcs-1jf"))

    def test_hyphen_insert(self):
        self.assertIn("GA-2100-1A1", _normalize_forms("GA2100-1A1"))

    def test_no_region_stripping(self):
        # 正規化では region を剥がさない (canonical=suffix込み)
        forms = _normalize_forms("DW-6900RCS-1JF")
        self.assertTrue(all(f.endswith("JF") for f in forms))


class TestLookupFailClosed(unittest.TestCase):
    """実 catalog DB に対する fail-closed 挙動 (dedupe 後の実データ前提)."""

    def test_suffix_canonical_hit(self):
        # bare が dedupe 削除済の suffix canonical → exact 解決
        rec = lookup_gshock("DW-6900RCS-1JF")
        self.assertIsNotNone(rec)
        self.assertEqual(rec["product_id"], "DW-6900RCS-1JF")

    def test_suffix_input_lowercase_hit(self):
        rec = lookup_gshock("dw-6900rcs-1jf")
        self.assertIsNotNone(rec)
        self.assertEqual(rec["product_id"], "DW-6900RCS-1JF")

    def test_bare_with_twin_returns_none(self):
        # bare 'DW-6900RCS-1' は suffix twin (DW-6900RCS-1JF) 在り → 1:N 曖昧 → None
        self.assertTrue(_has_region_twin("DW-6900RCS-1"))
        self.assertIsNone(lookup_gshock("DW-6900RCS-1"))

    def test_bare_only_canonical_hit(self):
        # suffix twin 無しの bare-only canonical → 解決 (73% を壊さない)
        self.assertFalse(_has_region_twin("G-7900A-4"))
        rec = lookup_gshock("G-7900A-4")
        self.assertIsNotNone(rec)
        self.assertEqual(rec["product_id"], "G-7900A-4")

    def test_gbx_100_2_restored_color2_not_twin_of_2AJF(self):
        # ★round-1 誤削除事故の再発防止:
        # GBX-100-2(色2) は GBX-100-2AJF(色2A) の twin ではない (末尾A=色).
        # よって bare 入力 GBX-100-2 は解決でき、None にならないこと.
        self.assertFalse(_has_region_twin("GBX-100-2"))
        rec = lookup_gshock("GBX-100-2")
        self.assertIsNotNone(rec)
        self.assertEqual(rec["product_id"], "GBX-100-2")

    def test_gbx_100_2AJF_suffix_hit(self):
        rec = lookup_gshock("GBX-100-2AJF")
        self.assertIsNotNone(rec)
        self.assertEqual(rec["product_id"], "GBX-100-2AJF")

    def test_empty_returns_none(self):
        self.assertIsNone(lookup_gshock(""))
        self.assertIsNone(lookup_gshock(None))  # type: ignore


if __name__ == "__main__":
    unittest.main()
