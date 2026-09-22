"""PSA10 の `Gem Mint` を禁止ワード `mint` で弾かない (2026-09-22 / Act 提案1)。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "iMakeBayAPI"))
from listing_common import banned_title_words_in as B          # noqa: E402

W = ["mint", "gem mt", "gem-mt", "l@@k"]


def test_gem_mint_passes():
    assert B("Pikachu 025/165 Japanese PSA 10 Gem Mint", W) == []


def test_plain_mint_and_near_mint_still_banned():
    assert B("Pikachu Mint Condition PSA 10", W) == ["mint"]
    assert B("Pikachu Near Mint", W) == ["mint"]
    assert B("Pikachu Gem Mint Mint", W) == ["mint"]


def test_gem_mt_still_banned():
    assert B("Pikachu PSA 10 GEM MT", W) == ["gem mt"]
