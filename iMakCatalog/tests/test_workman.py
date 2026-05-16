"""Workman scraper の unit test + catalog 整合性."""
from __future__ import annotations
import json, sqlite3, sys, unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))
sys.path.insert(0, str(_REPO / "scrapers"))

from scrapers import workman  # noqa
import api  # noqa


class TestHinbanFromFullId(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(workman._hinban_from_full_id("g2300018604015"), "18604")
        self.assertEqual(workman._hinban_from_full_id("g2300035345090"), "35345")
        self.assertEqual(workman._hinban_from_full_id("g2300067171032"), "67171")

    def test_invalid(self):
        self.assertIsNone(workman._hinban_from_full_id(""))
        self.assertIsNone(workman._hinban_from_full_id("g123"))
        self.assertIsNone(workman._hinban_from_full_id("not_g"))


class TestHinbanFromImageUrl(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(
            workman._hinban_from_image_url("https://workman.jp/img/goods/S/35345_t1.jpg"),
            "35345",
        )
        self.assertEqual(
            workman._hinban_from_image_url("https://workman.jp/img/goods/L/18604_main.jpg"),
            "18604",
        )

    def test_invalid(self):
        self.assertIsNone(workman._hinban_from_image_url(""))
        self.assertIsNone(workman._hinban_from_image_url("https://example.com/foo.jpg"))


class TestWorkmanCatalogIntegrity(unittest.TestCase):
    """catalog 内 workman entry の必須 field を保証."""

    def test_all_have_hinban_and_name(self):
        conn = sqlite3.connect(str(api._DB_PATH))
        cur = conn.cursor()
        cur.execute("SELECT product_id, name, specs FROM products WHERE category='workman'")
        bad = []
        for pid, name, sj in cur.fetchall():
            specs = json.loads(sj or "{}")
            if not pid.startswith("workman:"):
                bad.append((pid, "product_id 形式不正"))
            if not specs.get("hinban"):
                bad.append((pid, "hinban 欠落"))
            if not name:
                bad.append((pid, "name 欠落"))
        conn.close()
        if bad:
            msg = "workman entry integrity issues:\n"
            for pid, err in bad[:20]:
                msg += f"  {pid}: {err}\n"
            self.fail(msg)


if __name__ == "__main__":
    unittest.main()
