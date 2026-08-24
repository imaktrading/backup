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

RE_LOOKUP_POKEMON = r"\ndef lookup_pokemon\(.*?(?=\ndef )"


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


class TestAccentFolding(unittest.TestCase):
    """PSA ラベルは ASCII でしか書けないので、`é` を含む名前を畳んでから比べる.

    回答書 `requests/2026-08-24_hq_pokemon_name_guard_response.md` の
    「アクセント畳みを同時に入れる」条件。畳まないと照合を入れた意味が逆になる
    (`Poké Kid` `Flabébé` のような正しい行を弾いてしまう)。
    """

    def _rec(self, name_en, name_jp="", name=None):
        return {"name": name if name is not None else name_en,
                "name_jp": name_jp, "name_en": name_en}

    def test_accented_names_pass_against_ascii_label(self):
        # 2026-08-24 実測: 畳まないと pokemon で 25行 (全 franchise で 49行) が誤 reject
        for name_en, subject in (
            ("Flabébé", "FLABEBE"),
            ("Pokédex", "POKEDEX"),
            ("PokéVital A", "POKEVITAL A"),
            ("PokéNav", "POKENAV"),
            ("PokéHealer+", "POKEHEALER"),
            ("Poké Kid", "POKE KID"),
            ("Kämpfer", "KAMPFER"),
        ):
            with self.subTest(name_en):
                self.assertTrue(
                    pc._record_name_matches_subject(self._rec(name_en), subject),
                    f"{name_en} が ASCII ラベル {subject!r} で弾かれた")

    def test_folding_does_not_open_the_gate(self):
        # 畳んでも別人は通さない (畳みは取りこぼしを減らすだけで、穴にしない)
        self.assertFalse(
            pc._record_name_matches_subject(self._rec("Flabébé"), "FLOETTE"))
        self.assertFalse(
            pc._record_name_matches_subject(self._rec("Ortega"), "ARVEN SUPER"))

    def test_empty_after_folding_is_dropped(self):
        # 畳んで空/2文字以下になったトークンは捨てる。空文字は必ず部分一致するので
        # 残すと照合そのものが素通りになる
        self.assertFalse(
            pc._record_name_matches_subject(self._rec("Ortega"), "ピカチュウ ARVEN"))

    def test_ascii_names_are_unchanged(self):
        self.assertEqual(pc._fold_ascii("PIKACHU"), "PIKACHU")
        self.assertEqual(pc._fold_ascii("Flabébé"), "FLABEBE")


class TestRejectIsLogged(unittest.TestCase):
    """弾いた時に理由を1行出す (回答書の追加要求). 他3ゲームと同じ形にする."""

    def test_pokemon_reject_prints_the_same_line_as_the_others(self):
        src = (_REPO / "integrations" / "psa_to_csv.py").read_text(encoding="utf-8")
        m = re.search(RE_LOOKUP_POKEMON, src, re.S)
        self.assertIsNotNone(m)
        body = m.group(0)
        self.assertIn("名前不一致 → reject", body,
                      "reject の理由が走行ログに出ない (出品くんが追えない)")


if __name__ == "__main__":
    unittest.main()
