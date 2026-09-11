# -*- coding: utf-8 -*-
"""探索・廃盤の起こしで入れた UT に 色の一覧が無かった件の回帰テスト (2026-09-11).

Advisor 依頼 `requests/2026-09-11_ut_color_variants_missing.md`: 男性・男女兼用で 529件、
`color_variants` / `ebay_colors` が無く、出品側が色を選べずに止まった。
detail API (と Wayback の product JSON) は colors / sizes / prices を持っているので、
検索 API の取り込みと同じ組み立て (`uniqlo_ut.specs_from_detail`) を通す。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scrapers"))

import uniqlo_ut as U  # noqa: E402

DETAIL = {   # E445600-000 の detail の形 (2026-09-11 実取得を縮めたもの)
    "productId": "E445600-000", "l1Ids": ["445600"], "name": "ミッキー スタンズ UT",
    "genderName": "unisex",
    "colors": [{"code": "COL00", "displayCode": "00", "name": "WHITE", "filterCode": "WHITE"}],
    "sizes": [{"code": "SMA004", "displayCode": "004", "name": "M"},
              {"code": "SMA007", "displayCode": "007", "name": "XXL"}],
    "prices": {"base": {"value": 1500}},
    "images": {"main": {"00": {"image": "https://image.uniqlo.com/x/goods_00_445600.jpg"}}},
}


def test_detail_gets_color_list_and_ebay_color():
    s = U.specs_from_detail(DETAIL)
    assert [c["name"] for c in s["color_variants"]] == ["WHITE"]
    assert s["color_variants"][0]["ebay_color"] == "White"
    assert s["ebay_colors"] == ["White"]
    assert [v["name"] for v in s["size_variants"]] == ["M", "XXL"]
    assert s["l1_id"] == "445600"
    assert s["price_jpy_base"] == 1500


def test_unisex_spelling_is_one():
    """検索 API の「男女兼用」と detail API の「unisex」を UNISEX にそろえる."""
    assert U.specs_from_detail(DETAIL)["gender"] == "UNISEX"
    assert U.specs_from_detail(dict(DETAIL, genderName="男女兼用"))["gender"] == "UNISEX"
    assert U.specs_from_detail(dict(DETAIL, genderName="男女兼用"))["department"] == "Unisex Adults"
