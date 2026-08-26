"""BASE SHOP リミテッドカードコレクション vol.1 の6枚を PSA から引けること (2026-08-26).

きっかけ: cert163955605 (2025 ONE PIECE JAPANESE LIMITED CARD COLLECTION VOL.1
#001 MONKEY D. LUFFY / PSA 10) が **候補に一切出なかった**。

判定 (1丁目1番地):
  ① カタログのデータ … 正しい。公式 (cardlist ?series=550801) を再取得して6枚と
     券面番号 (ST21-001 / OP08-001 / OP05-098 / OP06-021 / OP10-003 / OP10-042) を確認済。
  ② 引き方             … 誤り。PSA brand から set_code を取れず即 Skip していた。

★ここで固定する不変条件は2つ:
  1. 6枚がそれぞれ **その edition の行** に解決すること
  2. **番号と名前が合っている別カード** (base `P-001` = 限定商品収録カードのルフィ) を
     返さないこと。名前検証を素通りするので、これが一番危ない誤出品の形。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))

from integrations.psa_to_csv import lookup_one_piece  # noqa: E402

BRAND = "ONE PIECE JAPANESE LIMITED CARD COLLECTION VOL.1"
OFFICIAL = "ONE PIECEカードゲーム BASE SHOPリミテッドカードコレクションvol.1"

# (PSA card number, PSA subject, 期待 product_id)
CARDS = [
    ("001", "MONKEY D. LUFFY", "ST21-001_p2"),
    ("001", "TONY TONY CHOPPER", "OP08-001_p3"),
    ("098", "ENEL", "OP05-098_p4"),
    ("021", "PERONA", "OP06-021_p3"),
    ("003", "SUGAR", "OP10-003_p2"),
    ("042", "USOPP", "OP10-042_p3"),
]


class TestResolves(unittest.TestCase):
    def test_all_six_resolve(self):
        for num, subject, expected in CARDS:
            with self.subTest(card=f"#{num} {subject}"):
                r = lookup_one_piece(BRAND, num, subject, verbose=False)
                self.assertIsNotNone(r, f"#{num} {subject} が候補に出ない")
                self.assertEqual(r.get("card_id"), expected)

    def test_resolved_row_is_this_edition(self):
        """返った行の official set 名が この商品であること (別 edition の同番号でない)."""
        for num, subject, _ in CARDS:
            with self.subTest(card=f"#{num} {subject}"):
                r = lookup_one_piece(BRAND, num, subject, verbose=False) or {}
                self.assertEqual(r.get("set_name_official"), OFFICIAL)


class TestDoesNotMisResolve(unittest.TestCase):
    def test_does_not_return_generic_promo_luffy(self):
        """base `P-001` も「モンキー・D・ルフィ」= 名前検証を通ってしまう別カード."""
        r = lookup_one_piece(BRAND, "001", "MONKEY D. LUFFY", verbose=False) or {}
        self.assertNotEqual(r.get("card_id"), "P-001",
                            "番号と名前は合うが edition が違う別カードを返している = 誤出品")

    def test_unknown_vol_is_fail_closed(self):
        """catalog に無い vol を名指しされたら **出さない** (base P-001 に落ちない)."""
        r = lookup_one_piece("ONE PIECE JAPANESE LIMITED CARD COLLECTION VOL.2",
                             "001", "MONKEY D. LUFFY", verbose=False)
        self.assertIsNone(r, "未収録 vol なのに別カードを返している")


class TestResolverFacade(unittest.TestCase):
    def test_resolve_returns_canonical_key(self):
        import resolver  # noqa: E402
        got = resolver.resolve({
            "category": "one_piece_tcg",
            "signals": {"brand": BRAND, "card_no": "001", "subject": "MONKEY D. LUFFY"},
        })
        self.assertEqual(got, "ST21-001_p2")


if __name__ == "__main__":
    unittest.main()
