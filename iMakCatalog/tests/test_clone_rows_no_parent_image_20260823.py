"""clone 行に親の絵が入らないことの回帰テスト (2026-08-23).

回答書 `requests/2026-08-23_hq_go_cll_images_and_clone_hardening_response.md` §2。

事故: clone 行の `source_url` が親の series ページを指していたので、画像補完が
それを開いて **親カードの絵**を入れた。`OP01-077_GE` が3日連続で「画像なし」の
指摘として上がり続けた。`GD01-100_PB01` は note に「新規 Ito 画イラスト」と書いて
あるのに base `GD01-100` の画像3枚と byte 一致していた。

固定する不変条件:
  A) clone 行が消えていない (query が空振りしたら誤検知ゼロに見えるので件数も見る)
  B) `specs.cloned_from` が入っていて、その base 行が同じ category に実在する
  C) `source_url` が空 (親のページを指さない)
  D) images が base 行と一致しない (= 親の絵のコピーが無い)
  E) `clone_rows.is_clone` が clone 行だけ True を返す
  F) 画像補完の入口が clone_rows の判定を通っている (配線が外れたら赤)
"""
from __future__ import annotations

import json
import sqlite3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))

import api  # noqa: E402
import clone_rows  # noqa: E402

# 2026-08-23 実測。増える分には構わないが、減ったら行が消えている。
KNOWN_MIN = 5

_SQL = (r"SELECT id, category, product_id, source, source_url, images, specs "
        r"FROM products WHERE source LIKE '%clone\_%' ESCAPE '\' "
        r"   OR json_extract(specs,'$.cloned_from') IS NOT NULL")


def _rows():
    db = sqlite3.connect(api._DB_PATH)
    db.row_factory = sqlite3.Row
    rows = db.execute(_SQL).fetchall()
    bases = {}
    for r in rows:
        base = clone_rows.cloned_from(r["specs"], r["source"])
        b = db.execute("SELECT images FROM products WHERE category=? AND product_id=?",
                       (r["category"], base)).fetchone() if base else None
        bases[r["id"]] = (base, b)
    db.close()
    return rows, bases


def _imgs(raw):
    try:
        v = json.loads(raw or "[]")
    except (ValueError, TypeError):
        return []
    return v if isinstance(v, list) else []


class TestCloneRows(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.rows, cls.bases = _rows()

    def test_a_clone_rows_still_there(self):
        self.assertGreaterEqual(
            len(self.rows), KNOWN_MIN,
            f"clone 行が {len(self.rows)} 件しか取れない (2026-08-23 実測 {KNOWN_MIN} 件)。"
            "query が空振りすると『違反ゼロ』に見えるのでここで止める")

    def test_b_cloned_from_points_at_a_real_base(self):
        for r in self.rows:
            s = json.loads(r["specs"] or "{}")
            base, brow = self.bases[r["id"]]
            self.assertTrue(
                (s.get(clone_rows.SPEC_KEY) or "").strip(),
                f"{r['product_id']}: specs.cloned_from が無い")
            self.assertIsNotNone(
                brow, f"{r['product_id']}: base {base!r} が {r['category']} に無い")

    def test_c_source_url_is_empty(self):
        for r in self.rows:
            self.assertIn(
                r["source_url"], ("", None),
                f"{r['product_id']}: source_url={r['source_url']!r} "
                "(clone 行は空。親のページを指すと画像補完が親の絵を取る)")

    def test_d_images_are_not_a_copy_of_the_base(self):
        for r in self.rows:
            base, brow = self.bases[r["id"]]
            mine = _imgs(r["images"])
            if not mine or brow is None:
                continue
            self.assertNotEqual(
                mine, _imgs(brow["images"]),
                f"{r['product_id']}: images が base {base} と同じ = 親の絵のコピー")

    def test_e_is_clone_only_matches_clone_rows(self):
        for r in self.rows:
            self.assertTrue(clone_rows.is_clone(r["specs"], r["source"]),
                            f"{r['product_id']} が clone と判定されない")
        db = sqlite3.connect(api._DB_PATH)
        db.row_factory = sqlite3.Row
        plain = db.execute(
            "SELECT product_id, specs, source FROM products "
            "WHERE category='one_piece_tcg' AND product_id='OP01-077'").fetchone()
        db.close()
        self.assertIsNotNone(plain)
        self.assertFalse(clone_rows.is_clone(plain["specs"], plain["source"]),
                         "base 行 OP01-077 を clone と判定している")

    def test_f_image_backfill_paths_are_wired(self):
        """画像補完の入口が clone_rows の判定を通っていること (配線が外れたら赤)."""
        targets = (
            ROOT / "tools" / "backfill_pokemon_images.py",
            ROOT / "migrations" / "2026-08-22_set_name_fill_and_clone_images.py",
        )
        for p in targets:
            src = p.read_text(encoding="utf-8")
            self.assertIn("import clone_rows", src, f"{p.name}: clone_rows を import していない")
            self.assertIn("clone_rows.is_clone", src, f"{p.name}: is_clone を通していない")


if __name__ == "__main__":
    unittest.main()
