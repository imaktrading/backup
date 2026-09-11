"""目視で特定した UT の行は カタログの値を写す (2026-09-11 ユーザー「カタログの値」).

特定は iMakHQ/tools/ut_identify.py (人の目視)。tshirt_listing は台帳を見て、
色・素材・原産国・サイズ表などを写真から推測せずカタログから写す。
- 日本語を出品に出さない (訳が辞書に無ければ その行は出さない)
- 原産国2か国は Item Specifics 空欄 + 説明文に両方 (2026-09-09 決定)
"""
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
for p in (_ROOT / "iMakMercari", _ROOT / "iMakeBayAPI"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
import ut_catalog_values as V  # noqa: E402


def _prod(**over):
    s = {"gender": "MEN", "l1_id": "486160",
         "color_variants": [{"name": "WHITE", "displayCode": "00", "ebay_color": "White"},
                            {"name": "BLACK", "displayCode": "09", "ebay_color": "Black"}],
         "composition": "綿100%", "countries_of_origin": ["VN"], "fit": "Regular",
         "character_family": "Super Mario", "character": "Mario", "themes": ["Video Games", "Retro"],
         "size_chart_inch": [{"size": "XL", "length": "29 1/2", "shoulder": "20", "chest": "23 1/2",
                              "sleeve": "9"}],
         "collab": "スーパーマリオ"}
    s.update(over)
    return {"category": "uniqlo_ut", "product_id": "E486160-000", "name": "マリオ UT", "specs": s}


class TestMaterial:
    @pytest.mark.parametrize("comp,expect", [
        ("綿100%", ("Cotton", "100% Cotton")),
        ("100％ 綿", ("Cotton", "100% Cotton")),                        # 全角 ％
        ("60％ 綿，40％ レーヨン（モダール&reg;）", ("Cotton Blend", "60% Cotton, 40% Rayon")),
        ("本体:綿100%,リブ部分:綿71%・ポリエステル29%(リサイクルポリエステル繊維を100%使用)",
         ("Cotton", "100% Cotton")),                                    # 本体だけ見る
        ("88% ポリエステル, 12% ポリウレタン", ("Polyester Blend", "88% Polyester, 12% Polyurethane")),
        ("当商品は以下どちらかの組成商品をお送りいたします。<br>100% 綿 ( 25% リサイクル綿繊維を使用 )<br>100% 綿",
         ("Cotton", "100% Cotton")),                                    # 2通りでも同じなら採る
    ])
    def test_parse(self, comp, expect):
        assert V.main_material(comp) == expect

    def test_unknown_fiber_stops(self):
        """★日本語を黙って通さない."""
        with pytest.raises(V.NotListable, match="辞書に無い"):
            V.main_material("シルク100%")

    def test_two_different_compositions_stop(self):
        with pytest.raises(V.NotListable):
            V.main_material("当商品は以下どちらかの組成商品をお送りいたします。<br>100% 綿<br>50% 綿, 50% ポリエステル")

    def test_per_color_composition_stops(self):
        with pytest.raises(V.NotListable):
            V.main_material("[00 WHITE] 100% 綿 [09 BLACK] 90% 綿, 10% ポリエステル")


class TestEbayVocabulary:
    """★2026-09-11 Taxonomy API (15687) で確認した eBay の選択肢に合わせる."""

    def test_rayon_is_viscose_on_ebay(self):
        assert V.main_material("100% レーヨン") == ("Viscose", "100% Rayon")

    def test_blend_values_exist_only_for_cotton_and_polyester(self):
        assert V.main_material("76% 綿, 24% ナイロン")[0] == "Cotton Blend"
        assert V.main_material("60% レーヨン, 40% 綿")[0] == "Viscose"

    def test_country_value_drops_does_not_apply(self):
        """"Does not apply" は Country of Origin の選択肢に無い."""
        assert V.country_value("Does not apply") == ""
        assert V.country_value("Vietnam") == "Vietnam"
        assert V.country_value("ベトナム") == ""


class TestOrigin:
    def test_one_country(self):
        assert V.origin(["VN"]) == ("Vietnam", "Vietnam")

    def test_two_countries_leave_the_item_specific_empty(self):
        spec, line = V.origin(["CN", "VN"])
        assert spec == "" and "China or Vietnam" in line

    def test_unknown_code_is_not_guessed(self):
        assert V.origin(["ZZ"]) == ("", "")


class TestSize:
    @pytest.mark.parametrize("txt,jp", [("XL(LL)", "XL"), ("3XL(4L)", "3XL"), ("2XL(3L)", "XXL"),
                                        ("M", "M"), ("", ""), ("フリー", ""),
                                        # ★2026-09-12: サイズ欄が空でタイトルにしか無い出品
                                        ("⭐️ONE PIECE UNIQLO ユニクロTシャツ　XL⭐️", "XL"),
                                        ("新品 UNIQLO UT ONE PIECE Tシャツ Mサイズ", "M"),
                                        ("4XL(5L)以上", "4XL")])
    def test_jp_size(self, txt, jp):
        assert V.jp_size(txt) == jp

    def test_two_sizes_in_one_title_is_not_guessed(self):
        """違うサイズが2つ書いてあったら決めない (推測で出品しない)."""
        assert V.jp_size("ユニクロ UT Tシャツ M・L 2枚") == ""

    def test_title_is_the_last_resort(self):
        led = {"https://a": {"decision": "go", "product_id": "E1", "color": "WHITE", "size": ""}}
        import unittest.mock as m
        with m.patch.object(V, "load_product", lambda pid, db=None: _prod()):
            v = V.values_for_url("https://a", "", led, title="新品 UNIQLO UT ONE PIECE Tシャツ Mサイズ")
        assert v["size_jp"] == "M" and v["size_us"] == "S"


class TestBuildValues:
    def test_values(self):
        v = V.build_values(_prod(), "WHITE", "XL(LL)")
        sp = v["specs"]
        assert sp["Color"] == "White" and sp["Material"] == "Cotton" and sp["Model"] == "486160"
        assert sp["Country/Region of Manufacture"] == "Vietnam" and sp["Department"] == "Men"
        assert sp["Character Family"] == "Super Mario" and sp["Theme"] == "Video Games, Retro"
        assert v["size_jp"] == "XL" and v["size_us"] == "L"
        assert "29 1/2 in" in v["chart_html"]

    def test_no_japanese_in_listing_text(self):
        """★説明文・Item Specifics に日本語を1文字も出さない."""
        import re
        v = V.build_values(_prod(countries_of_origin=["CN", "VN"]), "BLACK", "XL")
        blob = " ".join([v["material_line"], v["origin_line"], v["chart_html"]]
                        + [str(x) for x in v["specs"].values()])
        assert not re.search(r"[぀-ヿ一-鿿]", blob), blob

    @pytest.mark.parametrize("over,color,size,msg", [
        ({"gender": "WOMEN"}, "WHITE", "XL", "性別"),
        ({"gender": "KIDS"}, "WHITE", "XL", "性別"),
        ({}, "PINK", "XL", "色"),
        ({}, "WHITE", "", "サイズ"),
        ({"composition": "シルク100%"}, "WHITE", "XL", "辞書"),
    ])
    def test_not_listable(self, over, color, size, msg):
        with pytest.raises(V.NotListable, match=msg):
            V.build_values(_prod(**over), color, size)

    def test_gu_is_not_listed_here(self):
        p = _prod()
        p["category"] = "gu"
        with pytest.raises(V.NotListable, match="GU"):
            V.build_values(p, "WHITE", "XL")


class TestLedger:
    def test_unidentified_row_is_untouched(self):
        assert V.values_for_url("https://x", "M", ledger={}) is None
        assert V.values_for_url("https://x", "M", ledger={"https://x": {"decision": "out"}}) is None

    def test_identified_but_missing_product_stops(self, monkeypatch):
        monkeypatch.setattr(V, "load_product", lambda pid, db=None: None)
        with pytest.raises(V.NotListable, match="カタログに無い"):
            V.values_for_url("https://x", "M", ledger={"https://x": {"decision": "go", "product_id": "E1"}})


class TestApply:
    def test_catalog_overrides_ai(self):
        from whitelist_registry import validate_and_normalize
        v = V.build_values(_prod(), "WHITE", "XL")
        out = V.apply_to_specs({"Color": "Ivory", "Material": "Cotton", "Brand": "Uniqlo",
                                "Department": "Unisex Adults"}, v, validate_and_normalize)
        assert out["Color"] == "White" and out["Department"] == "Men"

    def test_strict_mismatch_stops(self):
        def fake_validate(specs, cat):
            return specs, [("Department", specs["Department"], ["Men"], "not_in_whitelist")]
        v = V.build_values(_prod(), "WHITE", "XL")
        with pytest.raises(V.NotListable):
            V.apply_to_specs({}, v, fake_validate)


class TestCountryOfOriginColumn:
    """№137: Tシャツ (15687/53159) の eBay の項目名は Country of Origin."""

    def test_tshirt_uses_country_of_origin(self):
        src = (_ROOT / "iMakMercari" / "tshirt_listing.py").read_text(encoding="utf-8")
        assert '"C:Country of Origin"' in src
        assert '"C:Country/Region of Manufacture"' not in src
        assert "UCV.country_value(" in src

    def test_graniph_uses_country_of_origin_from_the_official_page(self):
        """★graniph は "Japan" 固定だった。実物は ベトナム/中国 (公式 PDP で確認)."""
        src = (_ROOT / "iMakMercari" / "graniph_csv_builder.py").read_text(encoding="utf-8")
        assert '"C:Country of Origin"' in src and '"Japan",  ' not in src
        import graniph_csv_builder as GB
        assert GB.country_jp_to_en("ベトナム") == "Vietnam" and GB.country_jp_to_en("中国") == "China"
        assert GB.country_jp_to_en("?") == ""

    def test_graniph_scraper_reads_origin(self):
        import graniph_scraper as GS
        html = "<dt>素材</dt><dd> 綿 100% </dd><dt>原産国</dt><dd> ベトナム </dd><dt>返品</dt>"
        assert GS._parse_origin(html) == "ベトナム"
        assert GS._parse_origin("<dt>素材</dt>") == ""


class TestWorkNames:
    """№138: 作品名は表で公式英語表記に同定。表に無ければ止める."""
    W = {"呪術廻戦": "Jujutsu Kaisen", "ドラえもん": "Doraemon", "ルーヴル美術館": "Louvre",
         "ポケモン": "Pokémon", "HUNTER×HUNTER": "Hunter x Hunter"}

    def test_lookup(self):
        assert V.work_name_en(["マンガUT 集英社創業100周年 /呪術廻戦"], self.W) == "Jujutsu Kaisen"
        assert V.work_name_en(["hunter × hunter"], self.W) == "Hunter x Hunter"

    def test_longest_key_wins(self):
        assert V.work_name_en(["ドラえもん ＆ ルーヴル美術館（UT）"], self.W) == "Louvre"

    def test_unknown(self):
        assert V.work_name_en(["佐藤可士和展"], self.W) == ""

    def test_real_table_loads_and_has_the_main_works(self):
        w = V.load_works()
        for jp, en in (("呪術廻戦", "Jujutsu Kaisen"), ("鬼滅の刃", "Demon Slayer"),
                       ("ポケモン", "Pokémon"), ("ONE PIECE", "One Piece")):
            assert w[jp] == en

    def test_unknown_work_is_not_listed(self):
        with pytest.raises(V.NotListable, match="対応表に無い"):
            V.build_values(_prod(collab="日本土産（NIPPON MIYAGE）", character_family=""), "WHITE", "XL")

    def test_character_family_is_the_table_value(self):
        v = V.build_values(_prod(collab="ポケモン", character_family="Pokemon"), "WHITE", "XL")
        assert v["specs"]["Character Family"] == "Pokémon" and v["work_en"] == "Pokémon"

    def test_title_check_ignores_accents_and_case(self):
        assert V.title_has("UNIQLO UT Pokemon Eevee T-Shirt", "Pokémon")
        assert V.title_has("UNIQLO UT HUNTER X HUNTER Tee", "Hunter x Hunter")
        assert not V.title_has("UNIQLO UT Pocket Monsters Tee", "Pokémon")

    def test_listing_skips_when_title_lacks_the_work(self):
        src = (_ROOT / "iMakMercari" / "tshirt_listing.py").read_text(encoding="utf-8")
        i = src.index('UCV.title_has(title_en, cat_v["work_en"])')
        assert "continue" in src[i:i + 200]


class TestGraniphTitle:
    def _p(self, ip="名探偵コナン", name="テスト｜ビッグシルエットTシャツ"):
        import graniph_scraper as GS
        return GS.GraniphProduct(item_code="019001564303", product_group_id="019001564",
                                 color_code="303", name_jp=name, description_jp="", material_jp="綿 100%",
                                 color_jp="ブラック", suggested_gender="unisex", price_regular_jpy=3000,
                                 price_sale_jpy=None, image_urls=[], sizes=["M"], size_all_declared=["M"],
                                 stock={"M": 1}, size_table=[], url="u", ip_jp=ip)

    def test_title_has_work_and_no_japan_exclusive(self):
        import graniph_csv_builder as B
        t = B.build_title(self._p())
        assert t.startswith("Detective Conan ") and "Graniph Japan" in t and "Exclusive" not in t
        assert t.endswith("NWT") and len(t) <= 80

    def test_unknown_ip_stops(self):
        import graniph_csv_builder as B
        with pytest.raises(V.NotListable):
            B.build_title(self._p(ip="架空の作品"))


class TestNoDuplicateListing:
    """★2026-09-12「補の概念とか重複出品とか PSA と同じ運用にするんだよ」(設計 iMakHQ/UT_FLOW.md).

    UT は 1出品 = 1色1サイズ。同じ商品・色・サイズが出品中なら出さず、補URLに回す。
    """
    LED = {"https://live": {"decision": "go", "product_id": "E1", "color": "BLUE", "size": "3XL(4L)"},
           "https://new": {"decision": "go", "product_id": "E1", "color": "BLUE", "size": "3XL"},
           "https://other": {"decision": "go", "product_id": "E1", "color": "BLUE", "size": "M"}}

    def _rows(self, aux=()):
        hdr = [""] * 33
        live = [""] * 33
        live[0], live[1] = "https://live", "358900000001"
        for i, u in enumerate(aux):
            live[28 + i] = u
        unlisted = [""] * 33
        unlisted[0] = "https://new"
        return [hdr, live, unlisted]

    def test_key_has_color_and_size(self):
        assert V.identity_key("E1", "blue", "3XL") == "uniqlo_ut:E1:BLUE:3XL"
        assert V.identity_key("E1", "", "3XL") == ""

    def test_listed_identity_is_found(self):
        got = V.listed_identities(self._rows(), self.LED)
        assert list(got) == ["uniqlo_ut:E1:BLUE:3XL"]
        assert got["uniqlo_ut:E1:BLUE:3XL"]["row"] == 2      # シートの行番号

    def test_unlisted_rows_are_not_counted(self):
        """B列が空 = まだ出していない → 止める相手にしない."""
        rows = self._rows()
        rows[1][1] = ""
        assert V.listed_identities(rows, self.LED) == {}

    def test_different_size_is_a_different_listing(self):
        got = V.listed_identities(self._rows(), self.LED)
        assert V.identity_key("E1", "BLUE", "M") not in got

    def test_aux_merge(self):
        assert V.merge_aux(["https://a"], "https://b") == ["https://a", "https://b"]
        assert V.merge_aux(["https://a"], "https://a") == ["https://a"]          # 二重に足さない
        full = [f"https://{i}" for i in range(5)]
        assert V.merge_aux(full, "https://x") == full                            # 5本で満杯

    def test_listing_skips_and_moves_to_aux(self):
        src = (_ROOT / "iMakMercari" / "tshirt_listing.py").read_text(encoding="utf-8")
        i = src.index("_live = ut_listed.get(_key)")
        body = src[i:i + 900]
        assert "UCV.merge_aux(" in body and "continue" in body
        assert "UCV.write_aux(ut_aux_add)" in src
        assert "ut_run[_key]" in src, "同じ走行に同じ物が2つあっても1つだけにする"


class TestListingWiring:
    SRC = (_ROOT / "iMakMercari" / "tshirt_listing.py").read_text(encoding="utf-8")

    def test_identified_rows_use_catalog(self):
        assert "UCV.values_for_url(target[\"url\"]" in self.SRC
        assert "specs = UCV.apply_to_specs(specs, cat_v, _wl_validate)" in self.SRC
        assert "cat=cat_v" in self.SRC

    def test_not_listable_is_skipped_not_guessed(self):
        i = self.SRC.index("cat_v = UCV.values_for_url")
        assert "continue" in self.SRC[i:i + 400]

    def test_two_country_origin_is_not_refilled(self):
        """★空欄にした原産国を、写真の読み取りや他人の出品の値で埋め直さない."""
        i = self.SRC.index("# Country of Origin: タグから読めた国名は尊重")
        assert "if not cat_v:" in self.SRC[i:i + 400]
        assert "if key in _from_cat:" in self.SRC
