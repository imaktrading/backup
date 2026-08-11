"""pcg-search.com 画像例外の回帰テスト (2026-08-10 制定 / 2026-08-11 反映).

依頼: iMak_data/catalog/requests/2026-08-10_pcg_search_images_for_official_gaps.md
回答: iMak_data/catalog/requests/2026-08-10_pcg_search_images_for_official_gaps_response.md

守る不変条件:
  A) BDK-005 / BDK-006 の images に pcg-search.com URL が入っている
     (公式に無いカードに限定した第三者 source 例外。ユーザー明示決定)
  B) source マーカーが `pcg_search_confirmed_20260810` を含む (案A 複合表記)
     → 後から第三者由来を辿れる形の担保
  C) images の JSON 形状が保たれている (list[str], 各要素が正しい pcg-search URL)
  D) CLAUDE.md に「第三者 source 例外規約」節が存在する
     (規約が失われて将来 SSOT 違反 flag が立つのを防ぐ)

**取ってよいのは画像のみ** — name / rarity / set 等の値は絶対に第三者から取らない。
"""
from __future__ import annotations
import json
import sqlite3
import sys
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO.parent))
sys.path.insert(0, str(_REPO))
import api  # type: ignore  # noqa: E402


EXPECTED_IMAGES = {
    "BDK-005": "https://pcg-search.com/img/pcg/pcgrb005.png",
    "BDK-006": "https://pcg-search.com/img/pcg/pcgrb006.png",
}
EXPECTED_SOURCE_MARKER = "pcg_search_confirmed_20260810"


class TestPcgSearchImageException(unittest.TestCase):

    def _row(self, product_id: str):
        con = sqlite3.connect(str(api._DB_PATH))
        try:
            return con.execute(
                "SELECT product_id, source, images "
                "FROM products WHERE product_id=? AND category='pokemon_tcg'",
                (product_id,)).fetchone()
        finally:
            con.close()

    def test_images_populated_with_pcg_search_url(self):
        for pid, expected_url in EXPECTED_IMAGES.items():
            row = self._row(pid)
            self.assertIsNotNone(row, f"{pid}: catalog に存在しない")
            _, _, images_json = row
            images = json.loads(images_json or "[]")
            self.assertIsInstance(images, list, f"{pid}: images が list でない")
            self.assertEqual(
                len(images), 1,
                f"{pid}: images は 1件のみ (実測 {len(images)})")
            self.assertEqual(
                images[0], expected_url,
                f"{pid}: 期待 {expected_url!r} 実測 {images[0]!r}")

    def test_source_marker_contains_pcg_search(self):
        for pid in EXPECTED_IMAGES:
            row = self._row(pid)
            self.assertIsNotNone(row, f"{pid}: catalog に存在しない")
            _, source, _ = row
            self.assertIn(
                EXPECTED_SOURCE_MARKER, source or "",
                f"{pid}: source={source!r} に {EXPECTED_SOURCE_MARKER!r} が含まれない "
                f"(第三者由来の識別が失われる)")


class TestPcgSearchExceptionDocumentedInClaudeMd(unittest.TestCase):
    """規約 (CLAUDE.md §画像の第三者 source 例外規約) が失われていないこと."""

    def test_exception_section_present(self):
        claude_md = _REPO / "CLAUDE.md"
        self.assertTrue(claude_md.exists(), "iMakCatalog/CLAUDE.md が見つからない")
        text = claude_md.read_text(encoding="utf-8")
        self.assertIn(
            "画像 (images) の第三者 source 例外規約", text,
            "CLAUDE.md に第三者 source 例外規約の節が無い "
            "(将来 SSOT 違反 flag が立つ)")
        self.assertIn(
            "pcg_search_confirmed_YYYYMMDD", text,
            "例外規約の source マーカー命名例が失われている")
        self.assertIn(
            "BDK-005", text,
            "適用実績 (BDK-005) の記載が失われている")
        self.assertIn(
            "BDK-006", text,
            "適用実績 (BDK-006) の記載が失われている")


if __name__ == "__main__":
    unittest.main()
