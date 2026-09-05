"""3rd ANNIVERSARY SET のカードを通常弾に取り違えないこと (2026-08-26).

きっかけ: cert151301749 (3RD ANNIVERSARY SET #079 LUFFY/KING OF PIRATES) が
**ブースターの OP12-079 を候補に出していた**。絵柄は通常版=フルカラー金枠、
現物=紫の単色・漫画コマ で別物。ユーザーが目視で気づいて止めた。

この商品はプレミアムバンダイ限定 (プロモ10種) で、**公式が収録一覧を出していない**。
だから 1st/2nd と違って行が自動で入らず、PSA の cert が出た1枚ずつ足す運用になる。

★固定する不変条件は2つ:
  1. 登録済の2枚は その edition の行に解決する
  2. **まだ登録していない番号は None** (= 出さない)。同番号の通常弾カードに落ちない。
     ここが落ちると「番号も名前も合う別カード」を出品してしまい、人も気づけない。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))

from integrations.psa_to_csv import lookup_one_piece  # noqa: E402

BRAND = "ONE PIECE JAPANESE 3RD ANNIVERSARY SET"
# ★2026-09-05: 公式がこの商品の収録一覧を出した。手作りの `_AN03` は公式の `_pN` に
#   一本化した (migrations/2026-09-05_an03_superseded_by_official.py)。
#   CLAUDE.md「公式が載せたら公式値で上書きする」どおりの入れ替え。
SET_OFFICIAL = "ONE PIECE カードゲーム 3rd ANNIVERSARY SET"

REGISTERED = [
    ("079", "LUFFY/KING OF PIRATES", "OP12-079_p1", "OP12-079"),
    ("118", "SABO", "OP07-118_p3", "OP07-118"),
    ("005", "PORTGAS D. ACE", "ST15-005_p2", "ST15-005"),   # 2026-08-29 cert152977069
]


class TestRegistered(unittest.TestCase):
    def test_resolves_to_anniversary_row(self):
        for num, subject, expected, _ in REGISTERED:
            with self.subTest(card=f"#{num} {subject}"):
                r = lookup_one_piece(BRAND, num, subject, verbose=False)
                self.assertIsNotNone(r, f"#{num} {subject} が候補に出ない")
                self.assertEqual(r.get("card_id"), expected)
                self.assertEqual(r.get("set_name_official"), SET_OFFICIAL)

    def test_does_not_return_the_booster_row(self):
        """通常弾の同番号 (別絵柄) を返さない = 誤出品しない."""
        for num, subject, _, booster in REGISTERED:
            with self.subTest(card=f"#{num} {subject}"):
                r = lookup_one_piece(BRAND, num, subject, verbose=False) or {}
                self.assertNotEqual(r.get("card_id"), booster)


class TestUnregisteredIsFailClosed(unittest.TestCase):
    """未登録の番号は **出さない**。base に落ちたら誤出品."""

    def test_unregistered_number_returns_none(self):
        for num, subject in (("001", "MONKEY D. LUFFY"), ("003", "TONY TONY CHOPPER")):
            with self.subTest(card=f"#{num} {subject}"):
                r = lookup_one_piece(BRAND, num, subject, verbose=False)
                self.assertIsNone(
                    r, f"#{num} が {r and r.get('card_id')!r} に落ちている "
                       f"(3rd ANNIVERSARY SET の行はまだ登録していない)")


class TestOtherAnniversarySetsStillResolve(unittest.TestCase):
    """回帰: 1st/2nd は公式が収録済なので今までどおり解決する."""

    def test_2nd_anniversary_sabo(self):
        r = lookup_one_piece("ONE PIECE JAPANESE 2ND ANNIVERSARY SET", "083", "SABO",
                             verbose=False)
        self.assertEqual((r or {}).get("card_id"), "OP04-083_p5")


if __name__ == "__main__":
    unittest.main()
