"""tests/test_image_url_join - 写真URL (G列) が 1文字ずつ割れないこと.

2026-08-18 事故: 移送ツールが スプシのセル (str) を `image_urls` に渡し、
`_build_row` が `"|".join(str)` = **1文字ずつ join** して 230 行を壊した
("https://..." → "h|t|t|p|s|:|/|/|...")。
"""
from __future__ import annotations

import pytest

import sheet_writer_amazon
from sheet_writer_amazon import COL_IMAGES
from tools.fix_image_url_column import is_broken, repair

pytestmark = pytest.mark.offline

U1 = "https://static.mercdn.net/item/detail/orig/photos/m1_1.jpg"
U2 = "https://static.mercdn.net/item/detail/orig/photos/m1_2.jpg"


def _images(item: dict) -> str:
    return sheet_writer_amazon._build_row(item)[COL_IMAGES - 1]


def test_list_is_joined_with_pipe():
    assert _images({"image_urls": [U1, U2]}) == f"{U1}|{U2}"


def test_string_is_kept_as_is():
    """str を渡されても 1 文字ずつ割らない (事故の再発防止)."""
    assert _images({"image_urls": f"{U1}|{U2}"}) == f"{U1}|{U2}"
    assert _images({"image_urls": U1}) == U1


def test_empty_is_empty():
    assert _images({}) == ""
    assert _images({"image_urls": []}) == ""


# --------------------------------------------------------------------------
# 復旧ツール
# --------------------------------------------------------------------------
def test_is_broken_detects_char_split():
    broken = "|".join(f"{U1}|{U2}")
    assert is_broken(broken)
    assert not is_broken(f"{U1}|{U2}")
    assert not is_broken("")


def test_repair_restores_original_including_separators():
    original = f"{U1}|{U2}"
    assert repair("|".join(original)) == original
