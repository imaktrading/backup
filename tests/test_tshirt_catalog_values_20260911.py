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
                                        ("M", "M"), ("", ""), ("フリー", "")])
    def test_jp_size(self, txt, jp):
        assert V.jp_size(txt) == jp


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
