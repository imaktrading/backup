# -*- coding: utf-8 -*-
"""メルカリ新品 UT の出品を **スキルの形** にする (2026-09-13 試走で発覚)。

ユーザー「これまでのスキルも使ってる？」→ 使っていなかった。Tシャツ新規は 2026-04 の古い作りのまま:
  - タイトル: `UNIQLO UT … US L (JP XL) NWT Japan New` (ブランド先頭 / 「Japan New」はスキルにも既存出品にも無い)
  - 説明文: サイズ表が無い (無い時は「サイズ表の画像を見て」と書くが画像は無い) / `Japan L (US M)` と JP が先

スキル (apparel-tee-listing / RUNBOOK §4 §6) の形:
  タイトル `[作品] [キャラ] Anime Graphic Tee UNIQLO UT Japan Exclusive [色] NWT`
  (例はバリエーション出品なのでサイズが無い。1出品1サイズなので色の後ろに `US M (JP L)` — ユーザー確定)
  説明文 コラボ紹介 / Product Specifications / **全サイズの実測表** / Fit note / 透け感 (公式に書いてあれば)
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT / "iMakHQ" / "tools", ROOT / "iMakMercari", ROOT / "iMakeBayAPI"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import ut_catalog_values as V  # noqa: E402

CHART = [{"size": s, "length": l, "shoulder": sh, "chest": c, "sleeve": sl} for s, l, sh, c, sl in [
    ("XS", "24 3/4", "16 1/2", "18", "16"), ("S", "25 1/2", "17 1/4", "19 1/4", "16 1/2"),
    ("M", "26 3/4", "17 3/4", "20 1/2", "17 1/4"), ("L", "28", "18 1/4", "21 3/4", "18"),
    ("XL", "29", "19", "23", "18 3/4"), ("XXL", "30", "19 3/4", "24 1/2", "19 1/2")]]


def _v(**kw):
    v = {"work_en": "Dragon Ball", "color_name": "BLACK", "size_jp": "M", "size_us": "S",
         "is_gu": False, "themes": ["Anime"], "size_chart": CHART, "fit": "Regular",
         "material_line": "100% Cotton", "origin_line": "Vietnam", "sheerness": ""}
    v.update(kw)
    return v


def test_title_follows_the_skill_word_order():
    t = V.title_for(_v(work_en="Bleach", color_name="WHITE", size_jp="L", size_us="M"),
                    character="Ichigo Kurosaki")
    # サイズを足すと83字 → スキルの取捨どおり まず「Exclusive」を落とす
    assert t == "Bleach Ichigo Kurosaki Anime Graphic Tee UNIQLO UT Japan White US M (JP L) NWT"
    assert len(t) <= 80 and t.endswith(" NWT")
    short = V.title_for(_v(work_en="Bleach", color_name="RED", size_jp="S", size_us="XS"), character="Ichigo")
    assert short == "Bleach Ichigo Anime Graphic Tee UNIQLO UT Japan Exclusive Red US XS (JP S) NWT"
    assert "Japan New" not in t and "Brand New" not in t


def test_long_title_drops_exclusive_then_character_words():
    t = V.title_for(_v(color_name="LIGHT BLUE"), character="Frieza Goku Vegeta")
    assert len(t) <= 80
    assert "Exclusive" not in t and t.startswith("Dragon Ball ")
    assert "Light Blue US S (JP M) NWT" in t


def test_non_anime_theme_has_no_anime_word():
    t = V.title_for(_v(work_en="Andy Warhol", themes=["Retro"]), character="")
    assert "Anime" not in t and "Graphic Tee UNIQLO UT" in t


def test_character_same_as_work_is_not_repeated():
    t = V.title_for(_v(work_en="Pokémon"), character="Pokemon")
    assert t.count("Pok") == 1


def test_size_label_is_us_first():
    assert V.size_label("L") == "US M (JP L)"
    assert V.size_label("XS") == "US XXS (JP XS)"


def test_missing_size_chart_does_not_block_listing():
    """ユーザー「除外したらあかんやん」: 実測表がカタログに無くても出品は止めない。
    表も「サイズ表の画像を見て」の嘘の案内も出さず、Fit note だけにする。"""
    assert V.has_size_chart(_v())
    assert not V.has_size_chart(_v(size_chart=[]))
    assert not V.has_size_chart(_v(size_jp="4XL"))
    html = V.description_html(_v(size_chart=[]))
    assert "Actual Measurements" not in html and "size chart images" not in html
    assert "measurements above" not in html
    assert "Fit note" in html and "US S (JP M)" in html
    # ユーザー「せめて (JP/US 対応表の画像) これくらいはいるんちゃう」: 実測表が無くても対応表は出す
    assert "Size Chart — Japan / US" in html
    for jp, us in (("S", "XS"), ("XL", "L"), ("4XL", "3XL")):
        assert f">{jp}</td>" in html and f">{us}" in html
    assert "S ← this item" in html          # JP M の行 = US S を強調


def test_description_has_full_chart_us_first_and_no_image_excuse():
    html = V.description_html(_v(), about_en="Goku and friends return to UT.")
    assert "About This Collaboration" in html and "Goku and friends" in html
    assert "Size Chart — Actual Measurements (inch)" in html
    for lab in ("US XXS (JP XS)", "US S (JP M)", "US XL (JP XXL)"):
        assert lab in html
    assert "<b>Size:</b> US S (JP M), Regular fit" in html
    assert "Japan M (US S)" not in html
    assert "size chart images" not in html
    assert "← this item" in html


def test_sheerness_only_when_official_says_so():
    assert V.sheerness_of("- トップスフィット: 普通<br>- 透け感: ややあり") == "Slight"
    assert V.sheerness_of("- トップスフィット: 普通") == ""
    assert "Sheerness" not in V.description_html(_v())
    assert "<b>Sheerness:</b> None" in V.description_html(_v(sheerness="None"))


def test_generator_uses_the_skill_format_for_identified_rows():
    import io
    src = io.open(ROOT / "iMakMercari" / "tshirt_listing.py", encoding="utf-8").read()
    assert "UCV.title_for(cat_v" in src
    assert "require_size_chart" not in src, "サイズ表が無い行を除外している (ユーザー: 除外したらあかん)"
    assert "_UCV.description_html(cat" in src
