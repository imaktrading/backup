"""廃盤 UT の柄の記録 (design_listable) から出品の値を作る (2026-10-06 ユーザー依頼「カタログ化して出品」)。

カタログに性別・色の一覧・素材・原産国が無い → 性別はメルカリの文字 (レディース等なら出さない・無ければ Men)、
色はメルカリの色の文字、素材・原産国は空欄。画像の色番号がメルカリの色と違えば出さない。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "iMakMercari"))
import pytest  # noqa: E402
import ut_catalog_values as U  # noqa: E402


def _p(**s):
    base = {"data_level": "design_listable", "collab": "鬼滅の刃"}
    base.update(s)
    return {"category": "uniqlo_ut", "product_id": "FP1-01", "name": "鬼滅", "specs": base}


def test_design_row_builds_from_mercari_text():
    v = U.build_values(_p(), "ブラック", "L", mercari_text="鬼滅の刃 UT メンズ")
    sp = v["specs"]
    assert sp["Color"] == "Black" and sp["Department"] == "Men"
    assert sp["Material"] == "" and sp["Country/Region of Manufacture"] == ""
    assert v["work_en"] == "Demon Slayer" and v["size_jp"] == "L"


def test_design_row_women_or_unknown_color_is_not_listed():
    with pytest.raises(U.NotListable):
        U.build_values(_p(), "ブラック", "L", mercari_text="レディース UT")
    with pytest.raises(U.NotListable):
        U.build_values(_p(), "", "L")                     # 色が分からない → 出さない


def test_normal_row_still_needs_catalog_gender():
    p = _p()
    p["specs"]["data_level"] = ""
    with pytest.raises(U.NotListable):
        U.build_values(p, "ブラック", "L")


def test_image_color_must_match():
    blue = ["https://image.uniqlo.com/x/goods_62_440690.jpg"]
    assert U.image_colors(blue) == {"Blue"}
    assert not U.design_image_color_ok(blue, "Black")
    assert U.design_image_color_ok(blue, "Blue")
    assert U.design_image_color_ok(["https://www.fashion-press.net/img/news/1/a.jpg"], "Black")   # 色番号なし
    assert U.image_colors(["https://im.uniqlo.com/images/jp/pc/goods/425620/item/09_425620_middles.jpg"]) == {"Black"}
