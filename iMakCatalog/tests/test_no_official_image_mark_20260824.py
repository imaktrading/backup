"""画像が空の行の終端マーク (`specs.no_official_image`) を固定する.

依頼 `requests/2026-08-24_hq_eb02_003_ch01_image_may_not_exist.md` §2 /
回答 同 `_response.md` [IMPLEMENT-GO]。

空欄が「まだ取っていない」と「原理的に無い」を兼ねていたので、HQ の自動依頼が同じ
カードを毎日投げ続けていた (EB02-003_CH01 が 3走行連続)。終端マークが付いた行は
「公式が絵を出していない = 目視不能 = 出品しない」で確定し、再依頼の対象にしない。

ネットワークは使わない。**現状の DB とマークの作り**だけを見る。
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
import no_official_image_audit as N  # type: ignore  # noqa: E402

CATEGORIES = ("one_piece_tcg", "pokemon_tcg")


def _empty_image_rows():
    db = sqlite3.connect(str(api._DB_PATH))
    db.row_factory = sqlite3.Row
    try:
        ph = ",".join("?" for _ in CATEGORIES)
        return db.execute(
            f"SELECT product_id, category, specs FROM products "
            f"WHERE category IN ({ph}) AND IFNULL(images,'[]') IN ('[]','')",
            list(CATEGORIES)).fetchall()
    finally:
        db.close()


class TestEveryEmptyRowIsExplained(unittest.TestCase):
    """空欄が残っていて理由が無い行を作らない (= 依頼が永久に再送される状態)."""

    def test_no_unexplained_empty_image_row(self):
        naked = []
        for r in _empty_image_rows():
            s = json.loads(r["specs"] or "{}")
            if not s.get(N.MARK_KEY):
                naked.append(r["product_id"])
        self.assertEqual(naked, [],
                         f"画像も終端マークも無い行が残っている: {naked[:10]}")

    def test_mark_carries_its_evidence(self):
        for r in _empty_image_rows():
            s = json.loads(r["specs"] or "{}")
            if not s.get(N.MARK_KEY):
                continue
            with self.subTest(r["product_id"]):
                self.assertTrue(s.get(f"{N.MARK_KEY}_reason"), "理由が無い")
                self.assertTrue(s.get(f"{N.MARK_KEY}_checked_at"), "確認日が無い")
                self.assertIn(f"{N.MARK_KEY}_probe", s, "何を叩いたかが無い")


class TestMarkIsNotStuckOnRowsThatHaveImages(unittest.TestCase):
    """絵が入った行にマークが残っていない (マークを墓場にしない)."""

    def test_rows_with_images_are_not_marked(self):
        db = sqlite3.connect(str(api._DB_PATH))
        try:
            bad = [pid for pid, in db.execute(
                "SELECT product_id FROM products "
                "WHERE json_extract(specs,'$.no_official_image')=1 "
                "AND IFNULL(images,'[]') NOT IN ('[]','')")]
        finally:
            db.close()
        self.assertEqual(bad, [], f"絵が入ったのにマークが残っている: {bad[:10]}")


class TestEb02003Ch01(unittest.TestCase):
    """毎日の再依頼の発端。絵が入ったので終端マークは付かない."""

    def test_has_a_review_image(self):
        rec = api.lookup("one_piece_tcg", "EB02-003_CH01")
        self.assertIsNotNone(rec)
        self.assertTrue(rec.get("images"), "目視用の画像が入っていない")
        db = sqlite3.connect(str(api._DB_PATH))
        try:
            sp, = db.execute("SELECT specs FROM products WHERE product_id=?",
                             ("EB02-003_CH01",)).fetchone()
        finally:
            db.close()
        s = json.loads(sp or "{}")
        self.assertFalse(s.get(N.MARK_KEY), "絵が有るのに終端マークが付いている")
        self.assertIn("review_image_note", s, "第三者画像である印が無い")


class TestClassicMappingIsNotByNumber(unittest.TestCase):
    """Classic は番号で対応付けない (deck 番号は弾コード順でなく、並び順も番号順でない).

    2026-08-24 の実データ: CLK-001 は deck3-9 / CLL-001 は deck2-9。
    番号で当てると 17行を「取れる」と誤判定した。
    """

    def test_deck_number_does_not_follow_the_set_code(self):
        db = sqlite3.connect(str(api._DB_PATH))
        try:
            got = dict(db.execute(
                "SELECT product_id, images FROM products "
                "WHERE product_id IN ('CLK-001','CLL-001')"))
        finally:
            db.close()
        self.assertIn("deck-card-3-9.png", got["CLK-001"])
        self.assertIn("deck-card-2-9.png", got["CLL-001"])

    def test_spare_images_block_the_mark(self):
        # 未割当の絵が残っている間は終端マークを付けない (fail-closed)
        ok, reason, _ = N.classify_pokemon_classic("CLF-011", {"x.png"})
        self.assertTrue(ok)
        self.assertIn("未割当", reason)
        ok, _, _ = N.classify_pokemon_classic("CLF-011", set())
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
