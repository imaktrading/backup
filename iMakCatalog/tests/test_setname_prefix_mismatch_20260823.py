# -*- coding: utf-8 -*-
"""弾コード食い違い検知 (§0) が生きていること.

2026-08-22 に SV4K/SV4M/SV9 の 322枚が別セットの名前で出た。
**変換表そのものが誤っていると §6 の canonical ズレ検知では捕まらない** (derive も同じ誤りになる)。
この面だけが捕まえられるので、0件で維持する。
"""
import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location(
    "audit_mod", ROOT / "tools" / "set_name_integrity_audit.py")
audit_mod = importlib.util.module_from_spec(spec)
sys.modules["audit_mod"] = audit_mod
spec.loader.exec_module(audit_mod)


class TestPrefixMismatch(unittest.TestCase):
    def test_norm_code(self):
        """0埋めと大小は同じ弾として扱う."""
        n = audit_mod._norm_code
        self.assertEqual(n("SV03"), n("SV3"))
        self.assertEqual(n("Cp5"), n("CP5"))
        self.assertNotEqual(n("SV4K"), n("SV5K"))

    def test_live_zero(self):
        """本番データで 0件 (増えたら別セットの名前が入っている)."""
        for cat in ("pokemon_tcg", "one_piece_tcg", "dragonball_scg", "gundam_tcg"):
            res = audit_mod.audit([cat])
            prefix_mismatch = res[-1]
            self.assertEqual(prefix_mismatch, [], f"{cat}: 別セット名 {prefix_mismatch[:3]}")


if __name__ == "__main__":
    unittest.main()
