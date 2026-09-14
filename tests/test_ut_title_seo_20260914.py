# -*- coding: utf-8 -*-
"""メルカリ新品 UT のタイトルを SEO の語順・取捨で組む (2026-09-14)。

ユーザー「削るというか、SEO的に最適な語の組み合わせをしてほしい」→ 見本を見て「おｋ」。
前の作りの事故 (試走 9/14):
  - 80字を超えると「Japan Exclusive」→「Japan」だけが残る → 日本製と読める・原産国 Vietnam と矛盾で 11件除外
  - キャラ名を後ろの語から削り「Dragon Ball Goku, Anime …」と読点が残った
eBay 検索上位 (uniqlo ut one piece / dragon ball / pokemon 各50件) の語の使われ方:
  T-Shirt 50〜72% / Tee 4〜24% / Exclusive 0〜2% / Men・Mens 20〜40%
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT / "iMakMercari", ROOT / "iMakeBayAPI"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import ut_catalog_values as V  # noqa: E402


def _v(**kw):
    v = {"work_en": "Dragon Ball", "color_name": "ORANGE", "size_jp": "M", "size_us": "S", "is_gu": False,
         "themes": ["Anime"], "specs": {"Department": "Men"}}
    v.update(kw)
    return v


def test_split_characters_without_leaving_commas():
    assert V.character_names("Goku, Krillin") == ["Goku", "Krillin"]
    assert V.character_names("Luffy & Ace") == ["Luffy", "Ace"]
    assert V.character_names("Pokemon, Eevee", work="Pokémon") == ["Eevee"]
    t = V.title_for(_v(), character="Goku, Krillin")
    assert "," not in t and len(t) <= 80


def test_real_trial_titles():
    """9/14 の予約7件と同じ材料で。"""
    assert V.title_for(_v(color_name="BLACK", size_jp="M"), character="Frieza") == \
        "Dragon Ball Frieza Anime Graphic T-Shirt UNIQLO UT Black Men's US S (JP M) NWT"
    assert V.title_for(_v(work_en="One Piece", color_name="BEIGE"), character="Zoro") == \
        "One Piece Zoro Anime Graphic T-Shirt UNIQLO UT Beige Men's US S (JP M) NWT"
    two = V.title_for(_v(color_name="BLUE"), character="Goku, Vegeta")
    assert two.startswith("Dragon Ball Goku & Vegeta ") and len(two) <= 80


def test_priority_character_then_anime_then_department_then_japan_exclusive():
    short = V.title_for(_v(work_en="Naruto", color_name="RED", size_jp="S"), character="Naruto, Sasuke")
    assert "Sasuke Anime Graphic T-Shirt" in short and "Men's" in short
    # 余裕があれば Japan Exclusive は2語セットで入る (単独の Japan は出さない)
    tiny = V.title_for(_v(work_en="Ado", color_name="RED", size_jp="S", themes=["Music"], specs={}), character="")
    assert "Japan Exclusive" in tiny
    for t in (short, tiny):
        assert " Japan " not in t.replace("Japan Exclusive", "")


def test_required_words_always_present_and_unisex_word():
    t = V.title_for(_v(work_en="Demon Slayer", color_name="WHITE", size_jp="4XL", specs={"Department": "Unisex Adults"}))
    for w in ("Demon Slayer", "Graphic T-Shirt", "UNIQLO UT", "White", "US 3XL (JP 4XL)", "NWT"):
        assert w in t
    assert "Unisex" in t and t.endswith(" NWT")


def test_required_words_that_cannot_fit_stop_the_listing():
    with pytest.raises(V.NotListable):
        V.title_for(_v(work_en="X" * 60, color_name="LIGHT BLUE"))


def test_generator_prompt_matches():
    src = (ROOT / "iMakMercari" / "tshirt_listing.py").read_text(encoding="utf-8")
    assert "Anime Graphic T-Shirt UNIQLO UT [Color] [Men's|Unisex]" in src
    assert "Japan Exclusive [Color]" not in src
