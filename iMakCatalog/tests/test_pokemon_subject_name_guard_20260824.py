"""Pokemon の lookup に「PSA Subject と名前不一致 → reject」を入れたことを固定する.

経緯 (2026-08-24): 他の3カテゴリは前からこの照合を持っていたのに、**Pokemon だけ 0 箇所**で、
番号さえ合えば別カードでも通る状態だった (fail-closed の穴)。

    lookup_one_piece 3箇所 / lookup_gundam 3箇所 / lookup_dragonball 7箇所 / lookup_pokemon 0箇所

実測で安全性を確認してから入れた。目視で OK が付いた Pokemon cert 20件に対し:
    誤って弾く 0件 / 本物の誤りを 1件検出
    (cert80181108 SV3-130 が 'Arven'(=ペパー) になっていた -> 同日 'Ortega' に是正)
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))
sys.path.insert(0, str(_REPO / "integrations"))

import api  # type: ignore  # noqa: E402
import psa_to_csv as pc  # type: ignore  # noqa: E402


class TestGuardExists(unittest.TestCase):
    def test_all_four_lookups_check_the_name(self):
        src = (_REPO / "integrations" / "psa_to_csv.py").read_text(encoding="utf-8")
        for fn in ("lookup_pokemon", "lookup_one_piece",
                   "lookup_gundam", "lookup_dragonball"):
            m = re.search(rf"\ndef {fn}\(.*?(?=\ndef )", src, re.S)
            self.assertIsNotNone(m, fn)
            self.assertGreater(
                m.group(0).count("_record_name_matches_subject"), 0,
                f"{fn} に PSA Subject との名前照合が無い (fail-closed の穴)")


class TestGuardBehaviour(unittest.TestCase):
    def test_rejects_a_different_card(self):
        # SV3-130 は オルティガ。別人 (ペパー=Arven) の subject では通してはいけない
        rec = api.lookup("pokemon_tcg", "SV3-130")
        self.assertIsNotNone(rec)
        self.assertFalse(pc._record_name_matches_subject(rec, "ARVEN SUPER"))

    def test_accepts_the_right_card(self):
        rec = api.lookup("pokemon_tcg", "SV3-130")
        self.assertTrue(pc._record_name_matches_subject(rec, "ORTEGA SUPER"))

    def test_thin_subject_is_not_rejected(self):
        # subject からトークンが取れない時は照合をスキップ (取りこぼしを増やさない)
        rec = api.lookup("pokemon_tcg", "SV3-130")
        self.assertTrue(pc._record_name_matches_subject(rec, ""))


class TestOrtegaData(unittest.TestCase):
    def test_ortega_rows_fixed(self):
        import json
        import sqlite3
        db = sqlite3.connect(str(api._DB_PATH))
        try:
            rows = db.execute(
                "SELECT product_id, name_en, specs FROM products "
                "WHERE category='pokemon_tcg' AND name='オルティガ'").fetchall()
            self.assertTrue(rows)
            for pid, en, sp in rows:
                self.assertEqual(en, "Ortega", pid)
                self.assertEqual(json.loads(sp).get("character_name"), "Ortega", pid)
            # 本物のペパー (Arven) を巻き込んでいないこと
            n = db.execute("SELECT COUNT(*) FROM products WHERE category='pokemon_tcg' "
                           "AND name_en LIKE 'Arven%'").fetchone()[0]
            self.assertGreater(n, 0, "ペパー (Arven) まで消してしまっている")
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
