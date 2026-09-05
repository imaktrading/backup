# -*- coding: utf-8 -*-
"""C:Character に日本語を出さない (2026-09-05).

`specs.character_name` は eBay の `C:Character` の元で、**英語が入る欄**。
2026-09-05 実測で **3,500行が日本語のカード名**のままだった (`M4-001` に `ビードル`)。
出品側は写すだけなので、そのまま **日本語で eBay に出る**。

★英語名 (`name_en`) が無い行は空欄が正しいので、**日本語が入っている行だけ**を見張る。
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))
import api  # type: ignore  # noqa: E402

CATS = ("pokemon_tcg", "one_piece_tcg", "dragonball_scg", "gundam_tcg")
_JA = re.compile(r"[ぁ-んァ-ヶ一-龥]")


def _bad(cat: str):
    db = sqlite3.connect(str(api._DB_PATH))
    try:
        rows = db.execute(
            "SELECT product_id, name_en, specs FROM products WHERE category=? "
            "AND IFNULL(name_en,'')<>''", (cat,)).fetchall()
    finally:
        db.close()
    out = []
    for pid, en, sp in rows:
        cn = (json.loads(sp or "{}") or {}).get("character_name") or ""
        if cn and _JA.search(cn):
            out.append((pid, cn, en))
    return out


class TestCharacterIsEnglish(unittest.TestCase):
    def test_no_japanese_character_when_english_name_exists(self):
        for cat in CATS:
            with self.subTest(category=cat):
                bad = _bad(cat)
                self.assertEqual(bad, [], f"{cat}: character が日本語 {len(bad)}行 {bad[:3]}")


if __name__ == "__main__":
    unittest.main()
