"""§13 その種別が持ち得ない項目 — 0 で維持することを固定する.

外の正解表が要らない面 (Stage の §9 と同じ形)。2026-08-25 に実測で見つけた誤り:

    ポケモン Trainer-Item の hp  43行  「古びた〇〇の化石」の効果文 "HP60の…" を拾っていた
    ワンピ  Leader の cost      105行  Leader はコストでなく「ライフ」。8/22 の修正が
                                        variant (`_p` / `_P`) を取りこぼしていた

★「一部だけ持っている」は正常なこともある (ガンダムの Pilot は AP/HP 修正を持つ個体が在る)。
  0 でなければならない組み合わせだけを表に書く。
"""
from __future__ import annotations

import json
import sqlite3
import sys
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))
sys.path.insert(0, str(_REPO / "tools"))

import api  # type: ignore  # noqa: E402
import set_name_integrity_audit as A  # type: ignore  # noqa: E402


class TestAudit(unittest.TestCase):
    def test_zero(self):
        res = A.audit(["pokemon_tcg", "one_piece_tcg", "dragonball_scg"])
        self.assertEqual(res.type_forbidden, [],
                         f"種別が持ち得ない項目 {len(res.type_forbidden)} 行: "
                         f"{res.type_forbidden[:3]}")

    def test_table_is_not_empty(self):
        self.assertTrue(A._TYPE_FORBIDDEN, "禁止表が空 = 何も見張っていない")


class TestFixedRows(unittest.TestCase):
    def test_fossil_cards_have_no_hp(self):
        # 化石はグッズ。効果文の HP60 はカードの HP ではない
        for pid in ("M3-068", "M3-069"):
            rec = api.lookup("pokemon_tcg", pid)
            if rec is None:
                continue
            self.assertEqual(rec["specs"].get("card_type_ebay"), "Trainer-Item", pid)
            self.assertIn(rec["specs"].get("hp_ebay"), (None, ""), pid)

    def test_leader_variants_use_life_not_cost(self):
        for pid in ("OP13-001_p", "OP06-022_P"):
            rec = api.lookup("one_piece_tcg", pid)
            if rec is None:
                continue
            s = rec["specs"]
            self.assertEqual(s.get("card_type_ebay"), "Leader", pid)
            self.assertIn(s.get("cost"), (None, ""), f"{pid}: Leader に cost")
            self.assertTrue(s.get("life"), f"{pid}: life が空")

    def test_base_rows_untouched(self):
        # 8/22 に直した base 行を壊していないこと
        rec = api.lookup("one_piece_tcg", "OP13-001")
        if rec is not None:
            self.assertEqual(rec["specs"].get("life"), "4")
            self.assertIn(rec["specs"].get("cost"), (None, ""))


if __name__ == "__main__":
    unittest.main()
