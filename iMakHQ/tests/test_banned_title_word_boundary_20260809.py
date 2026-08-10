"""禁止ワードの照合は単語境界 — 部分一致に戻さない回帰テスト (2026-08-09)。

事故: check_csv が `if banned in title_lower` (部分一致) で照合していたため、
"Shenron" の中の "nr" (= No Reserve) に反応し、¥79,000 / $799 の Dragon Ball
(PSA10-158452540) が「禁止ワード 'nr'」で **出品から物理除外**された。

生成側 (psa_to_csv:1066) は元から単語境界で照合していた。単語リストだけ4カテゴリに
コピーして、照合ルールをコピーしなかったのが真因 = ②(引き方)の誤り。
照合を listing_common.banned_title_words_in に1本化した。

Shenron は DBSCG の頻出カードなので、直すまで永久に出品されない状態だった。
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_ROOT, "iMakeBayAPI"))

from listing_common import banned_title_words_in  # noqa: E402

WORDS = ["gem mt", "gem-mt", "gemmt", "mint", "graded", "l@@k", "look", "wow", "nr"]


def test_shenron_is_not_a_banned_word():
    """事故そのもの。'Shenron' の 'nr' に反応してはいけない。"""
    title = "PSA 10 Dragon Ball Wish for Shenron #FB07-097 2025 Japanese Card"
    assert banned_title_words_in(title, WORDS) == []


def test_standalone_nr_is_still_caught():
    """本来の禁止対象 (NR = No Reserve) は落とし続ける。"""
    assert banned_title_words_in("PSA 10 Charizard NR Auction", WORDS) == ["nr"]
    assert banned_title_words_in("psa 10 nr", WORDS) == ["nr"]


def test_words_embedded_in_longer_words_are_not_banned():
    """部分一致に戻ると全部 ERROR になる語 (実在しうるタイトル)。"""
    for title in ("PSA 10 Pokemon Sminthe Card",          # mint
                  "PSA 10 One Piece Unraveled Journey",   # nr x2
                  "PSA 10 Overlooked Rare Card",          # look
                  "PSA 10 Upgraded Holo"):                # graded
        assert banned_title_words_in(title, WORDS) == [], title


def test_real_banned_words_are_caught():
    assert banned_title_words_in("PSA 10 GEM MT Charizard", WORDS) == ["gem mt"]
    assert banned_title_words_in("PSA 10 Near Mint Card", WORDS) == ["mint"]
    assert banned_title_words_in("PSA 10 L@@K Rare Card", WORDS) == ["l@@k"]
    assert banned_title_words_in("PSA 10 WOW Card", WORDS) == ["wow"]
    assert banned_title_words_in("PSA 10 Graded Card", WORDS) == ["graded"]


def test_hyphen_and_digit_boundaries():
    """記号入り / 数字隣接。'gem-mt' は拾い、'FB07-097' のような番号は拾わない。"""
    assert banned_title_words_in("PSA 10 GEM-MT 10 Card", WORDS) == ["gem-mt"]
    assert banned_title_words_in("PSA 10 Card #FB07-097 2025", WORDS) == []
    assert banned_title_words_in("PSA 10 nr2 Card", WORDS) == []      # 数字が続く=別語


def test_empty_and_none_are_safe():
    assert banned_title_words_in("", WORDS) == []
    assert banned_title_words_in(None, WORDS) == []
    assert banned_title_words_in("PSA 10 Card", [None, ""]) == []


def test_all_category_checkers_delegate_to_listing_common():
    """4カテゴリの check_csv が自前で照合を再実装していないこと。

    ここが崩れる = 「リストだけ同期して照合はズレる」の再発。
    """
    import re
    for rel in ("iMakTCG/check_csv.py", "iMakMercari/check_csv.py",
                "iMak_ichibankuji/check_csv.py", "iMakG-shock/check_csv.py"):
        src = open(os.path.join(_ROOT, rel), encoding="utf-8").read()
        assert "banned_title_words_in" in src, rel
        # 素の部分一致に戻っていないこと
        assert not re.search(r"if\s+banned\s+in\s+title_lower", src), rel
