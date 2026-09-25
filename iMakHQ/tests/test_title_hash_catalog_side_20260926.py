"""タイトルに # が無い: C:Card Number が空ならカタログ依頼、在ればプログラム依頼 (2026-09-26)。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
from csv_auditor import is_catalog_side_title_msg, title_format_checks  # noqa: E402

H = ["*Title", "C:Card Number"]


def _msg(row):
    msgs = title_format_checks(H, row, "tcg")
    assert len(msgs) == 1
    return msgs[0]


def test_empty_card_number_goes_to_catalog():
    row = ["PSA 10 One Piece Promo Cards Uta", ""]
    assert is_catalog_side_title_msg(H, row, _msg(row))


def test_card_number_present_is_still_program_bug():
    row = ["PSA 10 One Piece Promo Cards Uta", "OP11-067"]
    assert not is_catalog_side_title_msg(H, row, _msg(row))


def test_other_messages_are_untouched():
    assert not is_catalog_side_title_msg(H, ["x", ""], "タイトル形式逸脱: 'CASIO G-Shock' で始まっていない")
