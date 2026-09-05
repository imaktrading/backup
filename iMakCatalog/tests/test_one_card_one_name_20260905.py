# -*- coding: utf-8 -*-
"""同じカードに英語名は1つ (2026-09-05).

2026-09-05 実測で、同じ日本語名に英語名が2つ以上あるものが **34件**あった。
中身は2種類:

  1. 別のカードの英語名が混ざっている (兄弟デッキの取り違えと同じ形)
       基本水エネルギー -> 'Bellibolt'(ハラバリー) が 7行
       博士の研究       -> 'Poké Kid'(ポケモンごっこ) が 1行
  2. 書き方の揺れ (`Monkey.D.Luffy` / `Monkey D. Luffy`)

1 は **誤出品**になる (絵と英語名が別のカード)。2 は eBay の Card Name が揃わない。

★これは「割れている」だけで見つかる。外の正解表が要らないので、ここで固定する。
"""
from __future__ import annotations

import sqlite3
import sys
import unittest
from collections import defaultdict
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))
import api  # type: ignore  # noqa: E402

# 日本語名を持つ列はカテゴリで違う (ワンピの `name` は英語のことがある)
CATS = {"pokemon_tcg": "name", "one_piece_tcg": "name_jp",
        "dragonball_scg": "name_jp", "gundam_tcg": "name_jp"}


def _split(cat: str, col: str):
    db = sqlite3.connect(str(api._DB_PATH))
    try:
        rows = db.execute(
            f"SELECT {col}, name_en FROM products WHERE category=? "
            f"AND IFNULL({col},'')<>'' AND IFNULL(name_en,'')<>''", (cat,)).fetchall()
    finally:
        db.close()
    by = defaultdict(set)
    for jp, en in rows:
        by[jp].add(en)
    return {k: sorted(v) for k, v in by.items() if len(v) > 1}


class TestOneCardOneName(unittest.TestCase):
    def test_no_card_has_two_english_names(self):
        for cat, col in CATS.items():
            with self.subTest(category=cat):
                bad = _split(cat, col)
                self.assertEqual(
                    bad, {}, f"{cat}: 1カードに英語名が2つ以上 "
                             f"{list(bad.items())[:3]}")


if __name__ == "__main__":
    unittest.main()
