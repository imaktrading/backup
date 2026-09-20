# -*- coding: utf-8 -*-
"""公式突合が「同じ番号の別バージョン」を1枚ずつ見分けられることの回帰テスト (2026-09-20).

守りたいこと: PRB 再録のように **同じ番号でパラレルと通常が並ぶ**弾で、
公式のレアリティを枝番 (`_p3` / `_r1`) ごとに持てること。
これが畳まれると、誤った行が正しい行に隠れて検出できない
(2026-09-20 実測: PRB-02 で 5行 誤っているのに差分0と出ていた)。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import official_drift_check as D  # noqa: E402


def block(no: str, variant: str, rarity: str, name: str) -> str:
    return (f'<dl class="modalCol">'
            f'<img src="https://www.onepiece-cardgame.com/images/cardlist/card/{variant}.png?260828">'
            f'<div class="infoCol"><span>{no}</span> | <span>{rarity}</span> | <span>CHARACTER</span></div>'
            f'<div class="cardName">{name}</div></dl>')


PAGE = ("<html>"
        + block("EB02-061", "EB02-061_r1", "SEC", "サボ")
        + block("EB02-061", "EB02-061_p3", "SPカード", "サボ")
        + "</html>")


class VariantAwareParse(unittest.TestCase):
    def test_both_variants_survive(self):
        cards = D.parse_cards(PAGE)
        self.assertEqual(len(cards), 2, "同じ番号の2バージョンが1枚に畳まれている")

    def test_variant_from_image_name(self):
        got = {c["variant"]: c["rarity"] for c in D.parse_cards(PAGE)}
        self.assertEqual(got, {"EB02-061_r1": "SEC", "EB02-061_p3": "SPカード"})

    def test_variant_absent_is_empty_not_crash(self):
        page = ('<dl class="modalCol"><div class="infoCol"><span>OP01-001</span> | '
                '<span>L</span></div><div class="cardName">ルフィ</div></dl>')
        cards = D.parse_cards(page)
        self.assertEqual(cards[0]["variant"], "")


if __name__ == "__main__":
    unittest.main()
