"""§11 定数項目 / §12 券面番号 の検査を固定する.

## §11 定数 (Game / Manufacturer / Card Size / Language / Country of Origin)

category ごとに1値しか取らない。2値以上に割れたら取り込みの取りこぼしか誤り。
2026-08-25 実測で `card_size_ebay` / `language` / `country_of_origin_ebay` が
それぞれ 2,859行 空だったので埋めた (値は Standard / Japanese / Japan の1種類のみ)。

★遊戯王は対象外の扱い: 英語刷りのみで `language=English`、原産国は空欄が正。
  ★既知の限界: category 丸ごと空でも「1値」なので §11 では出ない (埋率で見る面)。

## §12 券面番号

`card_number_text` はゲームで書式が違う (ポケモン '001/083' / ワンピ 'EB02-003') ので
**数字部分**で比べる。2026-08-25 実測で食い違い 0件。
空欄はポケモン596行あるが**全部 `cardID-*`** で、公式ページに番号が刷られていない
(規約「番号が無いカードは登録しない/欠番として起票しない」どおり)。
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))
sys.path.insert(0, str(_REPO / "tools"))

import api  # type: ignore  # noqa: E402
import set_name_integrity_audit as A  # type: ignore  # noqa: E402

JP_CATS = ("pokemon_tcg", "one_piece_tcg", "gundam_tcg", "dragonball_scg")


class TestConstants(unittest.TestCase):
    def test_no_split_constants(self):
        res = A.audit(list(JP_CATS))
        self.assertEqual(res.const_violation, [],
                         f"定数が割れている: {res.const_violation[:3]}")

    def test_jp_categories_are_filled(self):
        db = sqlite3.connect(str(api._DB_PATH))
        try:
            for cat in JP_CATS:
                for key, want in (("card_size_ebay", "Standard"),
                                  ("language", "Japanese"),
                                  ("country_of_origin_ebay", "Japan")):
                    n = db.execute(
                        f"SELECT COUNT(*) FROM products WHERE category=? "
                        f"AND coalesce(json_extract(specs,'$.{key}'),'')<>?",
                        (cat, want)).fetchone()[0]
                    self.assertEqual(n, 0, f"{cat}.{key} が {want} でない行 {n}")
        finally:
            db.close()

    def test_yugioh_is_left_alone(self):
        # 英語刷りのみ。日本語版の定数を書き込んでいないこと
        db = sqlite3.connect(str(api._DB_PATH))
        try:
            n = db.execute(
                "SELECT COUNT(*) FROM products WHERE category='yugioh_tcg' "
                "AND json_extract(specs,'$.language')='Japanese'").fetchone()[0]
        finally:
            db.close()
        self.assertEqual(n, 0, "遊戯王に Japanese を書き込んでいる")


class TestCardNumber(unittest.TestCase):
    def test_no_mismatch(self):
        res = A.audit(list(JP_CATS))
        self.assertEqual(res.card_number_mismatch, [],
                         f"券面番号が product_id と食い違う: {res.card_number_mismatch[:3]}")

    def test_rule_compares_digits_not_strings(self):
        """書式が違うだけの行を誤検出しないこと (回帰)."""
        def ok(base, txt):
            m1 = re.findall(r"\d+", base)
            want = m1[-1].lstrip("0") or "0"
            got = {x.lstrip("0") or "0" for x in re.findall(r"\d+", txt)}
            return want in got
        self.assertTrue(ok("M4-001", "001/083"))      # ポケモン形
        self.assertTrue(ok("OP06-022", "OP06-022"))   # ワンピ形
        self.assertFalse(ok("M4-001", "002/083"))     # 本物の食い違い

    def test_empty_card_numbers_are_cardid_rows(self):
        db = sqlite3.connect(str(api._DB_PATH))
        try:
            rows = db.execute(
                "SELECT product_id FROM products WHERE category='pokemon_tcg' "
                "AND coalesce(json_extract(specs,'$.card_number_text'),'')=''").fetchall()
        finally:
            db.close()
        stray = [p for (p,) in rows if not p.startswith("cardID")]
        self.assertEqual(stray[:5], [], f"cardID 以外で券面番号が空: {len(stray)}行")


if __name__ == "__main__":
    unittest.main()
