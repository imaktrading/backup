"""ポケモンの型は `specs.type_en` の1つだけ (2026-09-01).

きっかけ: CLK-008 / CLF-002 / CLF-015 の `C:Type` が空で出品できなかった。
値は在ったが、キー名が **`type`** で出品くんが読む `type_en` ではなかった
(依頼 `requests/2026-09-01_hq_cl_series_type_key_naming.md`)。

キー名が2つあると「値は在るのに渡らない」が起き、しかも**空欄と区別がつかない**。
手投入の行 (第三者裏取り) でだけ揺れていたので、名前を1つに寄せて回帰で固定する。
"""
from __future__ import annotations

import json
import sqlite3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import api  # noqa: E402

# 依頼で名指しされた行 (値が消えていないことを見る)
KNOWN = {"CLK-008": "Water", "CLF-002": "Grass", "CLF-015": "Colorless",
         "CLF-001": "Grass", "SM12a-214": "Psychic", "SM9a-067": "Fairy",
         "SM11-112": "Dragon"}


def _specs(where, args=()):
    db = sqlite3.connect(str(api._DB_PATH))
    db.row_factory = sqlite3.Row
    try:
        return [(r["product_id"], json.loads(r["specs"] or "{}"))
                for r in db.execute(
                    f"SELECT product_id, specs FROM products WHERE category='pokemon_tcg' "
                    f"AND {where}", args)]
    finally:
        db.close()


class TestOneKeyOnly(unittest.TestCase):
    def test_no_row_uses_the_legacy_key(self):
        bad = [pid for pid, s in _specs("json_extract(specs,'$.type') IS NOT NULL")
               if "type" in s]
        self.assertEqual(bad, [], f"`type` キーを持つ行が復活している: {bad[:10]}")


class TestValuesSurvived(unittest.TestCase):
    def test_known_rows_keep_their_value_under_type_en(self):
        ph = ",".join("?" for _ in KNOWN)
        got = dict(_specs(f"product_id IN ({ph})", tuple(KNOWN)))
        for pid, want in KNOWN.items():
            with self.subTest(pid):
                self.assertIn(pid, got, f"{pid} が消えている")
                self.assertEqual(got[pid].get("type_en"), want)


if __name__ == "__main__":
    unittest.main()
