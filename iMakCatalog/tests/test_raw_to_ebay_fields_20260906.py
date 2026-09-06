# -*- coding: utf-8 -*-
"""生値があるのに eBay 用の値が付いていない行を 0 に保つ (2026-09-06).

依頼: `requests/2026-09-06_ebay_aspect_fields_missing_on_new_ingests.md` (判定①)

## なぜ

`hp` / `stage` / `type_en` / `color` / `power` / `ap` は **公式の生値**で、
出品くんが読むのは `*_ebay` の方。落とす処理が **取り込みの一部になっていなかった**ため、
9/04〜9/05 に入れた行で HP / Stage / Attribute が空のまま CSV に出た (1,558行)。

## 何を見るか

`tools/finish_ingest.py` の PLAN (= 生値→eBay 語彙の規則) を使い、
**規則が値を出せるのに `*_ebay` が空**の行を数える。0 でなければ落ちる。

★`-` (公式の「なし」) や、eBay に対応する値が無い進化段階 (`V進化` 等) は
  規則が空を返すので、ここには出ない。**埋めるべき行だけ**を見張る。
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
import finish_ingest as F  # type: ignore  # noqa: E402


def _missing(cat: str):
    db = sqlite3.connect(str(api._DB_PATH))
    try:
        rows = db.execute("SELECT product_id, specs FROM products WHERE category=?",
                          (cat,)).fetchall()
    finally:
        db.close()
    out = []
    for pid, sp in rows:
        s = json.loads(sp or "{}")
        for dst, src, fn in F.PLAN.get(cat, []):
            if str(s.get(dst) or "").strip():
                continue
            raw = s.get(src)
            if raw is None or not str(raw).strip():
                continue
            if fn(raw):
                out.append((pid, src, raw, dst))
    return out


class TestRawToEbayFields(unittest.TestCase):
    def test_zero(self):
        for cat in ("pokemon_tcg", "one_piece_tcg", "dragonball_scg", "gundam_tcg"):
            with self.subTest(category=cat):
                bad = _missing(cat)
                self.assertEqual(bad, [], f"{cat}: eBay 用の値が付いていない {len(bad)}行 {bad[:3]}")


if __name__ == "__main__":
    unittest.main()
