"""Finish は空欄が正 (2026-08-22 ユーザー確定).

現物を見ないと決まらないので、レアリティやセットから推測して埋めてはいけない。
公式が「全カード foil」等と明記している商品だけ例外。

このテストは「良かれと思って一括で埋める」変更を落とすためにある。
0% は穴ではなく仕様。
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
import api  # noqa: E402

TCG = ("pokemon_tcg", "one_piece_tcg", "gundam_tcg", "dragonball_scg", "yugioh_tcg")

# 公式に裏が取れている出所だけが finish を持ってよい
ALLOWED_SOURCE_MARKS = ("crossconfirmed", "official", "confirmed", "pokemon_card_jp")


class TestFinishBlank(unittest.TestCase):
    def test_finish_filled_rows_are_few_and_sourced(self):
        """finish が入っている行は少数で、かつ出所が裏取り済であること."""
        con = sqlite3.connect(str(api._DB_PATH))
        try:
            bad, n_filled = [], 0
            for cat, src, sp in con.execute(
                    "SELECT category, source, specs FROM products WHERE category IN "
                    "(%s)" % ",".join("?" * len(TCG)), TCG):
                d = json.loads(sp) if sp else {}
                if not (d.get("finish") or "").strip():
                    continue
                n_filled += 1
                if not any(m in (src or "") for m in ALLOWED_SOURCE_MARKS):
                    bad.append((cat, src))
            self.assertEqual(
                bad[:5], [],
                f"裏取りの無い出所で finish が入っている ({len(bad)}行)。"
                f"推測で埋めていないか確認すること")
            # 一括で埋められたら気づけるように上限を置く
            self.assertLess(
                n_filled, 1000,
                f"finish が {n_filled} 行に入っている。"
                f"現物依存なので一括投入は誤り (CLAUDE.md『Finish は空欄が正』)")
        finally:
            con.close()


if __name__ == "__main__":
    unittest.main()
