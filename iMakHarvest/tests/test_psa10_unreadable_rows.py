"""tests/test_psa10_unreadable_rows - 鑑定番号が読めなかった分の扱い.

2026-08-18 user 指示: 写真から cert が読めなかった出品も捨てずに
**I列 (cert) 空欄** で中間スプシに入れる (目視で確認するため)。
出品くんの入口は 「I列非空」 なので、 空欄で入れる限り誤って出品には回らない。
"""
from __future__ import annotations

import pytest

from run_harvest_mercari_psa10 import build_sheet_items

pytestmark = pytest.mark.offline


def _cand(url: str, cert: str = "", readable: bool = True) -> dict:
    return {
        "url": url,
        "title": "PSA10 ルフィ",
        "price_jpy": 12345,
        "condition": "目立った傷や汚れなし",
        "description": "説明文",
        "image_urls": ["https://example.com/1.jpg"],
        "vision": {"cert": cert, "grade": "GEM MT 10"},
        "cert_readable": readable,
    }


def test_kept_rows_carry_cert():
    items = build_sheet_items([_cand("u1", cert="123456789")], [])
    assert len(items) == 1
    assert items[0]["cert"] == "123456789"
    assert items[0]["url"] == "u1"


def test_unreadable_rows_have_blank_cert():
    """番号が読めなかった行は I列空欄 (= 出品くんの入口に乗らない)."""
    items = build_sheet_items([], [_cand("u2", cert="", readable=False)])
    assert len(items) == 1
    assert items[0]["cert"] == ""
    # 目視できるよう 他の列 (タイトル/価格/写真/説明) は入っていること
    assert items[0]["title"] and items[0]["price_jpy"] and items[0]["image_urls"]
    assert items[0]["description"]


def test_both_are_written_in_one_batch():
    items = build_sheet_items([_cand("u1", cert="123456789")],
                              [_cand("u2", readable=False)])
    assert [i["url"] for i in items] == ["u1", "u2"]
    assert [i["cert"] for i in items] == ["123456789", ""]


def test_unreadable_never_borrows_another_cert():
    """読めなかった行に 他候補の cert が紛れ込まない (誤出品に直結するため)."""
    items = build_sheet_items([_cand("u1", cert="999888777")],
                              [_cand("u2", cert="999888777", readable=False)])
    assert items[1]["cert"] == ""
