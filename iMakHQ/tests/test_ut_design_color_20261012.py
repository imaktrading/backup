# -*- coding: utf-8 -*-
"""柄の記録 (design_listable) の色 — 2026-10-12 の自動出品で出た2つ。

1. タイトルに日本語の色 (m23226148693「… UNIQLO UT ブラック Men's …」) → 監査で除外 (B-20261012-010)
2. 色が空のまま確定した11件が「色がカタログの色に無い」で毎回止まり、決着済みなので画面にも二度と出なかった
"""
import os
import sys

_T = os.path.join(os.path.dirname(__file__), "..", "tools")
sys.path.insert(0, _T)
sys.path.insert(0, os.path.normpath(os.path.join(_T, "..", "..", "iMakMercari")))
import ut_catalog_values as UCV  # noqa: E402
import ut_identify as U  # noqa: E402

DESIGN = {"product_id": "E453662-000", "category": "uniqlo", "name": "ONE PIECE UT",
          "specs": {"data_level": "design_listable", "collab": "ONE PIECE", "l1_id": "453662"}}


def _values(color):
    try:
        return UCV.build_values(DESIGN, color, "M", mercari_text="メンズ", work_en="One Piece")
    except UCV.NotListable as e:
        return str(e)


def test_design_color_name_is_english():
    v = _values("ブラック")
    assert not isinstance(v, str), v
    assert v["specs"]["Color"] == "Black"
    assert v["color_name"] == "Black"
    assert v["color_from_jp"] == "ブラック"
    t = UCV.title_for(v)
    assert "ブラック" not in t and "Black" in t


def test_catalog_variant_color_unchanged():
    p = {"product_id": "E1-000", "category": "uniqlo", "name": "X UT",
         "specs": {"collab": "ONE PIECE", "gender": "men", "l1_id": "1",
                   "color_variants": [{"name": "09 BLACK", "ebay_color": "Black"}]}}
    try:
        v = UCV.build_values(p, "09 BLACK", "M", work_en="One Piece")
    except UCV.NotListable:
        return
    assert v["color_name"] == "09 BLACK" and v["color_from_jp"] == ""


def test_needs_color():
    assert U.needs_color({"decision": "go", "design": True, "color": ""})
    assert not U.needs_color({"decision": "go", "design": True, "color": "ホワイト"})
    assert not U.needs_color({"decision": "go", "color": ""})          # 色の一覧を持つ商品は別の道
    assert not U.needs_color({"decision": "nocat", "design": True})
    assert not U.needs_color(None)


def test_empty_color_design_row_comes_back_to_screen():
    w = U._WIDTH
    row = [""] * w
    row[U.C_URL] = "https://jp.mercari.com/item/m21518503946"
    src = [["h"] * w, row]
    led = {row[U.C_URL]: {"decision": "go", "design": True, "color": "", "product_id": "FP72769-01"}}
    assert [i for i, _r in U.pending_rows(src, led, set())] == [2]
    led[row[U.C_URL]]["color"] = "ホワイト"
    assert U.pending_rows(src, led, set()) == []


def test_confirm_screen_holds_design_without_color():
    src = open(os.path.join(_T, "ut_identify.py"), encoding="utf-8").read()
    assert "(dz&&!lcv)" in src
