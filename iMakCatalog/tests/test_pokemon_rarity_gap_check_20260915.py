"""ポケモンのレアリティ取りこぼし候補の回帰 (2026-09-15).

- 候補 = rarity が空 かつ 同じ弾の他の行に rarity が在る かつ 未確認
- 弾の全行が空 (公式が表示しない弾) は候補にしない
- 公式で確かめた印が付いた行は候補にしない
"""
import json
import sqlite3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "tools"), str(ROOT / "scrapers")]

import pokemon_rarity_gap_check as G  # noqa: E402


def _db(rows):
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE products (id INTEGER PRIMARY KEY, category TEXT, product_id TEXT, "
              "set_name_official TEXT, source_url TEXT, specs TEXT)")
    for i, (pid, son, specs) in enumerate(rows, 1):
        c.execute("INSERT INTO products VALUES (?,?,?,?,?,?)",
                  (i, "pokemon_tcg", pid, son, f"https://www.pokemon-card.com/card-search/details.php/card/{i}",
                   json.dumps(specs)))
    return c


class TestCandidates(unittest.TestCase):
    def test_gap_in_set_with_rarity(self):
        c = _db([("S4a-140", "S4a", {"rarity": "RR"}),
                 ("S4a-141", "S4a", {}),
                 ("S4a-142", "S4a", {"rarity_official_absent_checked_at": "2026-09-15"}),
                 ("SI-001", "SI", {}), ("SI-002", "SI", {})])
        got = [pid for _, pid, *_ in G.candidates(c)]
        self.assertEqual(got, ["S4a-141"])

    def test_audit_prints_section(self):
        src = (ROOT / "tools" / "set_name_integrity_audit.py").read_text(encoding="utf-8")
        self.assertIn("rarity_gap_unchecked=", src)
        self.assertIn("## 14. レアリティの取りこぼし候補", src)


if __name__ == "__main__":
    unittest.main()
