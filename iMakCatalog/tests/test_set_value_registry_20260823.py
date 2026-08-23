# -*- coding: utf-8 -*-
"""set_name_ebay に入ってよい値は2つだけ、を守る (2026-08-23 制定).

  ① eBay master (Game 別) に在る値
  ② `_free_text_set_values.yaml` に登録した値

2026-08-23 の事故: 英語版セット名 (`Sun & Moon—Celestial Storm` 等) が 1,729行に入って
いたのに、「Swsh で始まる値」という **見た目の条件**で確認して「0行」と報告していた。
条件を思いつけるかに依存する確認は必ず漏れるので、**許可された値の一覧と突き合わせる**。
"""
import importlib.util
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location(
    "audit_mod2", ROOT / "tools" / "set_name_integrity_audit.py")
audit_mod = importlib.util.module_from_spec(spec)
sys.modules["audit_mod2"] = audit_mod
spec.loader.exec_module(audit_mod)

BANNED = re.compile(r"^(Sun & Moon|Scarlet & Violet|Sword & Shield|Swsh|Black & White|"
                    r"Diamond & Pearl|HeartGold|Platinum)\s*[—\-–:]", re.I)
CATS = ("pokemon_tcg", "one_piece_tcg", "dragonball_scg", "gundam_tcg")


class TestSetValueRegistry(unittest.TestCase):
    def test_registry_loads(self):
        master, allow = audit_mod._load_allowed()
        self.assertTrue(master["pokemon_tcg"], "eBay master が読めていない")
        self.assertTrue(allow, "自由入力の登録簿が読めていない (yaml 壊れ?)")

    def test_no_unregistered_values(self):
        """未登録のセット名が 0件 (増えたら新しい誤りが入った合図)."""
        for cat in CATS:
            unregistered = audit_mod.audit([cat]).unregistered  # 位置ではなく名前で受ける
            n = sum(sum(v.values()) for v in unregistered.values())
            self.assertEqual(n, 0, f"{cat}: 未登録の値 {list(unregistered.get(cat, {}))[:3]}")

    def test_registry_has_no_english_series_names(self):
        """登録簿に英語版シリーズ名で始まる値が無い (ルール③)."""
        _, allow = audit_mod._load_allowed()
        for cat, vals in allow.items():
            bad = [v for v in vals if BANNED.match(v or "")]
            self.assertEqual(bad, [], f"{cat}: 英語版セット名が登録されている {bad}")


if __name__ == "__main__":
    unittest.main()
