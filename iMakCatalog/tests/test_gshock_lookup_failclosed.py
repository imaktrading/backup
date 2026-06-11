"""G-shock lookup_gshock alias 対応規約 test (2026-06-11 dedupe B案).

依頼: requests/2026-06-11_gshock_dedupe_switch_to_alias_link_B.md (HQ B案承認).
保証する alias 規約 (recall 重視・「曖昧な時だけ ''」):
  - suffix 形入力 → suffix canonical に exact 解決
  - bare 形 + alias_of 在り (1:1) → canonical に解決 ("" にしない = recall 維持)
  - bare 形 + 独立 canonical (alias_of NULL・twin 無し) → その bare を解決
  - bare 形 + 真の 1:N (alias_of NULL・twin 複数) → "" (None) 返却 (推測しない)
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


class TestLookupAlias(unittest.TestCase):
    """実 catalog DB に対する alias 対応挙動 (dedupe B案・実データ前提)."""

    def test_suffix_canonical_hit(self):
        # suffix canonical → exact 解決
        rec = lookup_gshock("GM-700G-9AJF")
        self.assertIsNotNone(rec)
        self.assertEqual(rec["product_id"], "GM-700G-9AJF")
        self.assertIsNone(rec.get("alias_of"))  # canonical 自身

    def test_bare_1to1_alias_resolves_to_canonical(self):
        # ★B案の核心: bare(1:1 alias) は canonical へ解決 ("" にしない = recall 維持)
        rec = lookup_gshock("GM-700G-9A")
        self.assertIsNotNone(rec)
        self.assertEqual(rec["product_id"], "GM-700G-9AJF")  # alias_of 先

    def test_bare_alias_lowercase_resolves(self):
        rec = lookup_gshock("gm-700g-9a")
        self.assertIsNotNone(rec)
        self.assertEqual(rec["product_id"], "GM-700G-9AJF")

    def test_true_1toN_returns_none(self):
        # bare 'GW-9400J-1B' は JF/JR 両 canonical = 真の 1:N・alias 一意化不可 → None
        self.assertTrue(_has_region_twin("GW-9400J-1B"))
        self.assertIsNone(lookup_gshock("GW-9400J-1B"))

    def test_bare_only_canonical_hit(self):
        # suffix twin 無しの bare-only canonical → 解決 (73% を壊さない)
        self.assertFalse(_has_region_twin("G-7900A-4"))
        rec = lookup_gshock("G-7900A-4")
        self.assertIsNotNone(rec)
        self.assertEqual(rec["product_id"], "G-7900A-4")

    def test_gbx_100_2_independent_color2(self):
        # ★round-1 誤削除事故の再発防止:
        # GBX-100-2(色2) は GBX-100-2AJF(色2A) の twin ではない (末尾A=色) →
        # 独立 canonical として自身に解決 (alias 化しない).
        self.assertFalse(_has_region_twin("GBX-100-2"))
        rec = lookup_gshock("GBX-100-2")
        self.assertIsNotNone(rec)
        self.assertEqual(rec["product_id"], "GBX-100-2")
        self.assertIsNone(rec.get("alias_of"))

    def test_gbx_100_2A_alias_of_2AJF(self):
        # GBX-100-2A(色2A) は GBX-100-2AJF の alias → canonical へ解決
        rec = lookup_gshock("GBX-100-2A")
        self.assertIsNotNone(rec)
        self.assertEqual(rec["product_id"], "GBX-100-2AJF")

    def test_gbx_100_2AJF_suffix_hit(self):
        rec = lookup_gshock("GBX-100-2AJF")
        self.assertIsNotNone(rec)
        self.assertEqual(rec["product_id"], "GBX-100-2AJF")

    def test_empty_returns_none(self):
        self.assertIsNone(lookup_gshock(""))
        self.assertIsNone(lookup_gshock(None))  # type: ignore


if __name__ == "__main__":
    unittest.main()
