"""EB02-003 チョッパー (『ONE PIECE CHOPPER's 1』同梱 promo) を 1行に保つ (2026-08-23).

窓口 GO: requests/2026-08-19_auto_catalog_add_one_piece_tcg_response.md
        requests/2026-08-18_hq_eb02_003_promo_missing_response.md
        →「同じ件なので、**どちらか1回で結構です**」

## ここで固定する不変条件は「在ること」ではなく「**1行だけ**であること」

2026-08-23 に **同じカードが 2つの内部ID で二重に入った**:

    EB02-003_P_choppers1   08:39 別セッションが投入 (PSA cert168544559 スラブ実写で確定)
    EB02-003_CH01          08:40 こちらが回答書の指定どおり投入 → 重複と判明したので取消

同じ物理カードが2行あると、PSA からの引き当てが候補2件になり、
CSV 出力が完全一致しない限り fail-closed reject (= 出品されない) に倒れる。
「行を足したのに出せないまま」という、依頼の目的と正反対の状態になる。

★どちらの内部ID を残すかは窓口の判断待ち
  (requests/2026-08-19_auto_catalog_add_one_piece_tcg_response_question.md)。
  ID が入れ替わってもこのテストは通る。**2行になった時だけ落ちる**ように書いてある。
"""
from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))

import api  # noqa: E402
from integrations.psa_to_csv import lookup_one_piece  # noqa: E402

PROMOS = "ONE PIECE JAPANESE PROMOS"


def _choppers_rows():
    """『ONE PIECE CHOPPER's 1』同梱 promo の行 (内部ID の付け方に依存しない)."""
    db = sqlite3.connect(api._DB_PATH, timeout=60)
    try:
        return db.execute(
            "SELECT product_id, set_name_official, "
            "       json_extract(specs,'$.set_name_ebay'), "
            "       json_extract(specs,'$.card_number_text') "
            "FROM products WHERE category='one_piece_tcg' "
            "  AND product_id LIKE 'EB02-003%' "
            "  AND set_name_official LIKE '%CHOPPER%'").fetchall()
    finally:
        db.close()


class TestExactlyOneRow(unittest.TestCase):
    def test_row_exists(self):
        self.assertTrue(_choppers_rows(),
                        "CHOPPER's 1 同梱 promo の行が無い (窓口 GO 済の欠落補充が消えた)")

    def test_not_duplicated(self):
        rows = _choppers_rows()
        self.assertEqual(
            len(rows), 1,
            "同じカードが複数行ある → PSA 引き当てが候補複数になり fail-closed で"
            "出品されない: %r" % ([r[0] for r in rows],))


class TestRowValues(unittest.TestCase):
    def test_card_number_is_base_number(self):
        """券面の印字は EB02-003 (内部ID の suffix は catalog 都合)."""
        for pid, _, _, num in _choppers_rows():
            self.assertEqual(num, "EB02-003", f"{pid} の card_number_text が {num!r}")

    def test_set_name_ebay_is_promo_cards(self):
        """通常セット名 (25th Anniversary Collection) に化けていないこと.

        set_name_official が filter_map / 自由文字列の登録から外れると derive が
        product_id prefix 'EB02' に fallback して通常セット名になる = promo なのに
        通常弾として誤出品。
        """
        for pid, _, ebay_val, _ in _choppers_rows():
            self.assertEqual(ebay_val, "Promo Cards",
                             f"{pid} の set_name_ebay が {ebay_val!r}")


class TestResolves(unittest.TestCase):
    """②(引き当て)側は **この依頼の範囲外**。ここでは安全性だけ固定する.

    ★2026-08-23 実測: 行を足しても PSA 引き当ては base の `EB02-003` を返す
      (promo fallback score=10 で base が勝つ)。= `_CH01` は候補に出ない。
      これは 2026-08-18 の回答書が既に HQ へ投げた ②側の宿題で、窓口の GO
      (「入れてください」) には含まれていない。**勝手に psa_to_csv を触らない**。
      窓口へ差し戻し中:
      requests/2026-08-19_auto_catalog_add_one_piece_tcg_response_question.md

    そのため「`_CH01` を返すこと」は**まだ assert しない** (通らないので嘘になる)。
    代わりに「**別のキャラを返さない**」= 誤出品しないことだけを固定する。
    """

    def test_does_not_return_a_different_character(self):
        """回帰: #003 の別カード (P-003 ユースタス・キッド) を返さない."""
        r = lookup_one_piece(PROMOS, "003", "TONY TONY CHOPPER", verbose=False)
        got = (r or {}).get("card_id") or (r or {}).get("product_id")
        self.assertNotEqual(got, "P-003", "別キャラのカードを返している = 誤出品")

    def test_returns_a_chopper_row_or_nothing(self):
        """返すなら必ずチョッパーの行。他キャラに落ちない (fail-closed は許容)."""
        r = lookup_one_piece(PROMOS, "003", "TONY TONY CHOPPER", verbose=False)
        if r is None:
            return  # fail-closed = 安全側
        self.assertEqual((r.get("name_en") or r.get("name")), "Tony Tony Chopper")


if __name__ == "__main__":
    unittest.main()
