# -*- coding: utf-8 -*-
"""タイトルから **本物のカード番号** を消さない (2026-08-18).

実害 (cert 151235549 / OP06-022 ヤマト = 週刊少年ジャンプ '24 #36-37 の付録プロモ):
    build_title  "… Wkly Shonen Jump '24-#36-37 #OP06-022 Yamato Promo Cards"
    旧 strip     "… Wkly Shonen Jump '24-#36-37 Yamato Promo Cards"
                 ↑ **雑誌の号数を残してカード番号を消した**
    → selfcheck が '#36' を card# と読んで PSA 022 と不一致 → 毎回 出品されず。

旧実装は「最初の '#' が card# のはず」という **位置の前提** だった。
セット名側に号数が入ると先頭が号数になるので、前提が崩れる。
card_number は引数で渡ってきているので **中身で選ぶ**。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from title_generation_agent import (  # noqa: E402
    _hash_is_card_number, _strip_non_card_hashes,
)

YAMATO = "PSA 10 One Piece Wkly Shonen Jump '24-#36-37 #OP06-022 Yamato Promo Cards"


class TestKeepsTheRealCardNumber:
    def test_magazine_issue_is_dropped_card_number_stays(self):
        for cn in ("022", "OP06-022"):     # 呼び元によってどちらも渡りうる
            got = _strip_non_card_hashes(YAMATO, cn)
            assert "#OP06-022" in got, f"card#={cn}: 本物のカード番号が消えている"
            assert "#36" not in got and "'24-" not in got, f"card#={cn}: 号数の残骸"

    def test_no_double_space_left_behind(self):
        got = _strip_non_card_hashes(YAMATO, "022")
        assert "  " not in got and got == got.strip()

    def test_plain_number_form(self):
        t = "PSA 10 Pokemon Japanese Celebrations #023/028 Flying Pikachu V"
        assert _strip_non_card_hashes(t, "023/028") == t

    def test_hyphen_form_untouched(self):
        t = "PSA 10 One Piece Pillars of Strength #OP03-070 Monkey D. Luffy"
        assert _strip_non_card_hashes(t, "070") == t

    def test_first_hash_kept_when_nothing_matches(self):
        """card# を指すものが1つも無ければ従来どおり先頭を残す (挙動を変えない)."""
        t = "PSA 10 Something #99 and #100 Card"
        got = _strip_non_card_hashes(t, "022")
        assert "#99" in got and "#100" not in got

    def test_empty_card_number_is_previous_behaviour(self):
        t = "PSA 10 Something #99 and #100 Card"
        got = _strip_non_card_hashes(t, "")
        assert "#99" in got and "#100" not in got

    def test_no_title_no_crash(self):
        assert _strip_non_card_hashes("", "022") == ""


class TestMatcher:
    def test_matches_bare_and_prefixed(self):
        assert _hash_is_card_number("#022", "022")
        assert _hash_is_card_number("#OP06-022", "022")
        assert _hash_is_card_number("#023", "023/028")

    def test_card_number_may_itself_carry_a_set_prefix(self):
        """呼び元が 'OP06-022' を渡すこともある (実測: 渡し方で結果が割れていた)."""
        assert _hash_is_card_number("#OP06-022", "OP06-022")
        assert not _hash_is_card_number("#36-37", "OP06-022")

    def test_leading_zeros_do_not_matter(self):
        assert _hash_is_card_number("#22", "022")

    def test_rejects_other_numbers(self):
        assert not _hash_is_card_number("#36-37", "022")
        assert not _hash_is_card_number("#100", "022")

    def test_empty_card_number_matches_nothing(self):
        assert not _hash_is_card_number("#022", "")


class TestSelfCheckNowPasses:
    """タイトルを直せば出品前チェックも通ること (症状側の実証)."""

    def test_validator_accepts_the_fixed_title(self):
        sys.path.insert(0, r"C:\dev\iMak\iMakeBayAPI")
        from listing_validator import validate_title_against_psa
        fixed = _strip_non_card_hashes(YAMATO, "022")
        errs = validate_title_against_psa(
            fixed, "ONE PIECE JAPANESE PROMOS", "022", catalog_set_name="Promo Cards")
        assert not [e for e in errs if "card#" in e], errs

    def test_validator_rejected_the_old_title(self):
        sys.path.insert(0, r"C:\dev\iMak\iMakeBayAPI")
        from listing_validator import validate_title_against_psa
        old = "PSA 10 One Piece Wkly Shonen Jump '24-#36-37 Yamato Promo Cards"
        errs = validate_title_against_psa(old, "ONE PIECE JAPANESE PROMOS", "022")
        assert any("card#" in e for e in errs), "旧タイトルは弾かれていたはず"
