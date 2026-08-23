"""ポケモン Classic (CLF/CLL/CLK) の画像が公式特設の正しい1枚であることの回帰テスト.

2026-08-23。回答書
`requests/2026-08-23_hq_go_cll_images_and_clone_hardening_response.md` §1。
発端は `PSA10-156684617` = `CLL-002 リザード` が画像なしで出品できなかったこと。

公式特設 (https://www.pokemon-card.com/ex/classic/index.html) の
`assets/images/deck-card-{1..3}-{1..10}.png` 30枚は **alt が空** なので、
画像を落として券面の日本語カード名を目視して割り当てた。ここが1つずれると
「別のカードの絵で目視照合する」= 誤出品になるので、割り当てを丸ごと固定する。

固定する不変条件:
  A) 割当表が 30 slot / 27行 で、product_id も slot も重複しない
  B) 27行の images が「その slot の公式URL 1枚」ちょうど
  C) `CLL-002` が deck-card-2-10.png (依頼そのもの)
  D) 割当表の券面名と catalog の name_jp が一致する (目視の結論が catalog と噛み合う)
  E) 割り当てなかった CL* 69行は images が空のまま (隣の絵で埋めない)
  F) URL が公式特設の下にある (第三者ホストに化けたら赤)
"""
from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))

import api  # noqa: E402

_MIG = ROOT / "migrations" / "2026-08-23_pokemon_classic_official_images.py"
_spec = importlib.util.spec_from_file_location("classic_images_20260823", _MIG)
mig = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mig)

CAT = "pokemon_tcg"
PREFIX = "https://www.pokemon-card.com/ex/classic/assets/images/"
MAPPED = {slot: (pid, label) for slot, (pid, label) in mig.MAPPING.items() if pid}


def _row(pid):
    db = sqlite3.connect(api._DB_PATH)
    db.row_factory = sqlite3.Row
    r = db.execute("SELECT product_id, name_jp, images FROM products "
                   "WHERE category=? AND product_id=?", (CAT, pid)).fetchone()
    db.close()
    return r


class TestClassicImageMapping(unittest.TestCase):

    def test_a_mapping_shape(self):
        self.assertEqual(len(mig.MAPPING), 30, "公式特設は 30 slot")
        self.assertEqual(len(MAPPED), 27, "うち3枚は基本エネルギーで catalog に行が無い")
        pids = [pid for pid, _ in MAPPED.values()]
        self.assertEqual(len(pids), len(set(pids)), "同じ product_id に2枚割り当てている")

    def test_b_each_mapped_row_has_exactly_its_slot_image(self):
        for slot, (pid, label) in MAPPED.items():
            r = _row(pid)
            self.assertIsNotNone(r, f"{pid} が catalog に無い")
            imgs = json.loads(r["images"] or "[]")
            self.assertEqual(
                imgs, [mig.image_url(slot)],
                f"{pid} ({label}) の images が {slot} の公式URL 1枚でない: {imgs!r}")

    def test_c_cll_002_charmeleon(self):
        """依頼そのもの (PSA10-156684617 / cert156684617)."""
        imgs = json.loads(_row("CLL-002")["images"] or "[]")
        self.assertEqual(imgs, [PREFIX + "deck-card-2-10.png"])

    def test_d_label_matches_catalog_name(self):
        """目視で読んだ券面名が catalog の name_jp と一致すること (ずれ検知)."""
        for slot, (pid, label) in MAPPED.items():
            self.assertEqual(_row(pid)["name_jp"], label,
                             f"{slot}: 券面 {label!r} と catalog の name_jp が違う")

    def test_e_unmapped_rows_stay_empty(self):
        """公式が画像を出していない 69行は空が正 (目視不能 = 出品しない)."""
        mapped = {pid for pid, _ in MAPPED.values()}
        db = sqlite3.connect(api._DB_PATH)
        rows = db.execute("SELECT product_id, images FROM products "
                          "WHERE category=? AND product_id LIKE 'CL%'", (CAT,)).fetchall()
        db.close()
        self.assertEqual(len(rows), 96, "CL* は 3デッキ x 32枚")
        others = [(p, i) for p, i in rows if p not in mapped]
        self.assertEqual(len(others), 69)
        for pid, imgs in others:
            self.assertIn(imgs, (None, "", "[]"),
                          f"{pid}: 公式に画像が無いのに何か入っている: {imgs!r}")

    def test_f_urls_are_official(self):
        for slot in MAPPED:
            self.assertTrue(mig.image_url(slot).startswith(PREFIX),
                            f"{slot}: 公式特設の URL でない")


if __name__ == "__main__":
    unittest.main()
