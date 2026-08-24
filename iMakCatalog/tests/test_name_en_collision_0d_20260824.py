"""§0d — 同じ英名を複数の日本語名が使っている、を毎日の監査に常設したことを固定する.

回答書 `requests/2026-08-24_hq_ortega_is_not_arven_response.md` §2 [IMPLEMENT-GO]。

なぜこの向きが要るか: オルティガ (SV3-104 / SV3-130 / SV8a-189) は3行とも `Arven` で
揃っていたので、逆向き (同じ日本語名が複数の英名を持つ) では**原理的に掛からない**。
別人の英名は必ず本人の行と衝突するので、この向きなら発生源で止まる。

★WARN のみ。自動修正はしない (表記ゆれの同一人物を誤って直す方が害が大きい)。
"""
from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))
sys.path.insert(0, str(_REPO / "tools"))

import api  # type: ignore  # noqa: E402
import set_name_integrity_audit as A  # type: ignore  # noqa: E402


class TestJpNameKey(unittest.TestCase):
    """表記ゆれの同一人物を畳む (畳まないと誤検知だらけで読めなくなる)."""

    def test_bracket_and_mark_are_folded(self):
        self.assertEqual(A.jp_name_key("ナッシー[Exeggutor]"), A.jp_name_key("ナッシー"))
        self.assertEqual(A.jp_name_key("シャワーズ☆"), A.jp_name_key("シャワーズ"))
        self.assertEqual(A.jp_name_key("ニドラン♀"), A.jp_name_key("ニドラン"))
        self.assertEqual(A.jp_name_key("ピカチュウ （プロモ）"), A.jp_name_key("ピカチュウ"))

    def test_different_people_are_not_folded(self):
        self.assertNotEqual(A.jp_name_key("ペパー"), A.jp_name_key("オルティガ"))


class TestSectionIsPermanent(unittest.TestCase):
    """節が消えないこと (0件でも出し続ける = 0 が続く証跡が唯一の証拠)."""

    def test_audit_returns_the_field(self):
        res = A.audit(["pokemon_tcg"])
        self.assertTrue(hasattr(res, "name_en_collision"), "§0d が AuditResult に無い")
        for row in res.name_en_collision:
            self.assertEqual(len(row), 3, row)          # (category, name_en, {name_jp: n})
            self.assertIsInstance(row[2], dict)

    def test_render_prints_the_section_even_when_empty(self):
        report = A.render([], [], [], [], {}, {}, {}, {}, [], {}, [], ["pokemon_tcg"])
        self.assertIn("## 0d.", report)
        self.assertIn("(なし)", report)

    def test_render_lists_the_groups(self):
        report = A.render([], [], [], [], {}, {}, {}, {}, [], {}, [], ["pokemon_tcg"],
                          [("pokemon_tcg", "Arven", {"ペパー": 30, "オルティガ": 3})])
        self.assertIn("`Arven`", report)
        self.assertIn("オルティガ:3", report)

    def test_marker_line_carries_the_count(self):
        src = (_REPO / "tools" / "set_name_integrity_audit.py").read_text(encoding="utf-8")
        self.assertIn("name_en_collision={len(name_en_collision)}", src,
                      "完走マーカーに件数が出ない (トレンドが追えない)")


class TestOrtegaIsGone(unittest.TestCase):
    """オルティガの是正を §0d 側からも固定する (再混入したらここが落ちる)."""

    def test_arven_no_longer_collides(self):
        res = A.audit(["pokemon_tcg"])
        hits = [x for x in res.name_en_collision if x[1] == "Arven"]
        self.assertEqual(hits, [], f"`Arven` を別人が使っている: {hits}")

    def test_arven_belongs_to_pepper_only(self):
        db = sqlite3.connect(str(api._DB_PATH))
        try:
            jps = {r[0] for r in db.execute(
                "SELECT DISTINCT name_jp FROM products "
                "WHERE category='pokemon_tcg' AND name_en='Arven'")}
        finally:
            db.close()
        self.assertTrue(jps)
        self.assertNotIn("オルティガ", jps)


class TestNoAutoFix(unittest.TestCase):
    """§0d は検知だけ。修正コードを持たせない."""

    def test_audit_is_select_only(self):
        src = (_REPO / "tools" / "set_name_integrity_audit.py").read_text(encoding="utf-8")
        for verb in ("UPDATE products", "DELETE FROM products", "INSERT INTO products"):
            self.assertNotIn(verb, src, f"監査が {verb} を持っている (WARN のみのはず)")


if __name__ == "__main__":
    unittest.main()
