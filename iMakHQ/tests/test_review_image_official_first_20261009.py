# -*- coding: utf-8 -*-
"""目視の画像は日本の公式サイトを最優先 (2026-10-09 P-102 ナミ: TCG+ の画像が別絵柄だった)。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
import post_psa_review as P

P102 = ["C:/dev/iMak_data/catalog/_official_images/one_piece_tcg/P-102.png",
        "https://www.onepiece-cardgame.com/images/cardlist/card/P-102.png",
        "https://files.bandai-tcg-plus.com/card_image/OP-JA/P/P-102_sample.png"]


def test_japanese_prefers_official_site():
    assert P._pick_image_by_language(P102, "ja") == P102[1]


def test_without_official_falls_back_to_ja_host():
    assert P._pick_image_by_language(P102[2:], "ja") == P102[2]


def test_english_official_site_is_not_taken_for_japanese():
    imgs = ["https://en.onepiece-cardgame.com/images/cardlist/card/P-102.png", P102[2]]
    assert P._pick_image_by_language(imgs, "ja") == P102[2]
