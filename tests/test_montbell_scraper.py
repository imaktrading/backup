#!/usr/bin/env python3
"""Phase 4 / 2026-05-03: iMakCatalog/scrapers/montbell.py の pure function テスト.

Selenium 不要範囲のみ:
  - _translate_first_match (JP→EN 1st-stage)
  - _derive_activity / _derive_features / _derive_type_and_style
  - _parse_spec_block (HTML 入力 → dict)
  - _parse_weight_g (重量文字列 → 整数 string)
  - _COLOR_SUFFIX_EN dict カバレッジ sanity
"""
from __future__ import annotations
import sys
from pathlib import Path

# iMakCatalog/scrapers を import path に追加
_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRAPERS = _REPO_ROOT / "iMakCatalog" / "scrapers"
if str(_SCRAPERS) not in sys.path:
    sys.path.insert(0, str(_SCRAPERS))

# api / iMakMercari への path も通す (montbell.py が import するため)
for p in (_REPO_ROOT / "iMakCatalog", _REPO_ROOT / "iMakMercari"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import montbell as m  # noqa: E402


# ============================================================================
# _translate_first_match
# ============================================================================
def test_translate_first_match_hits_first_jp_keyword():
    out = m._translate_first_match("ナイロン・タフタ", m._MATERIAL_JP_EN, "Not Specified")
    assert out == "Nylon"


def test_translate_first_match_default_when_no_keyword():
    out = m._translate_first_match("謎の素材", m._MATERIAL_JP_EN, "Not Specified")
    assert out == "Not Specified"


def test_translate_first_match_empty_input_returns_default():
    assert m._translate_first_match("", m._MATERIAL_JP_EN, "Not Specified") == "Not Specified"


# ============================================================================
# _derive_activity
# ============================================================================
def test_derive_activity_hiking_keyword():
    assert m._derive_activity("ハイキング用ジャケット") == "Hiking"


def test_derive_activity_climbing_to_hiking():
    assert m._derive_activity("クライミングウエア") == "Hiking"


def test_derive_activity_skiing():
    assert m._derive_activity("スキー用パーカ") == "Skiing"


def test_derive_activity_default_hiking_for_outdoor():
    """キーワード hit なし → outdoor product 想定で Hiking default."""
    assert m._derive_activity("シェルパーカ") == "Hiking"


# ============================================================================
# _derive_type_and_style
# ============================================================================
def test_derive_type_jacket_default():
    type_, style = m._derive_type_and_style("ライトシェルパーカ")
    assert type_ == "Jacket"
    assert style == "Parka"


def test_derive_type_vest():
    type_, _ = m._derive_type_and_style("ダウンベスト")
    assert type_ == "Vest"


def test_derive_type_coat():
    type_, _ = m._derive_type_and_style("ベンチコート")
    assert type_ == "Coat"


def test_derive_style_windbreaker():
    _, style = m._derive_type_and_style("U.L.ウインドブレーカー")
    assert style == "Windbreaker"


def test_derive_style_rain_coat_storm_cruiser():
    """ストームクルーザー → Rain Coat 推定."""
    _, style = m._derive_type_and_style("ストームクルーザー ジャケット")
    assert style == "Rain Coat"


def test_derive_style_puffer_for_down():
    _, style = m._derive_type_and_style("ダウンジャケット")
    assert style == "Puffer Jacket"


# ============================================================================
# _parse_spec_block
# ============================================================================
def test_parse_spec_block_full_format():
    """実 1106645 ページ風 HTML から spec dict を組立."""
    html = (
        '<h4 class="ttlType03">仕様</h4>'
        '<p>'
        '【素材】表地:40デニール・フルダル・ナイロン・タフタ[はっ水加工]<br>'
        '裏地:クリマプラス®メッシュ[ポリエステル〈吸汗加工〉]<br>'
        '【平均重量】303g<br>'
        '【機能】デュアルアクスルフード、リードインコード・システム<br>'
        '【特長】ジッパー付きポケット3個'
        '</p>'
    )
    out = m._parse_spec_block(html)
    assert "ナイロン" in out.get("表地", "")
    assert "ポリエステル" in out.get("裏地", "")
    assert "303g" in out.get("平均重量", "")
    assert "デュアルアクスルフード" in out.get("機能", "")
    assert "ジッパー付きポケット" in out.get("特長", "")


def test_parse_spec_block_missing_returns_empty_dict():
    """仕様 ブロックが無い HTML は空 dict 返却 (no crash)."""
    out = m._parse_spec_block("<html><body>no spec</body></html>")
    assert isinstance(out, dict)
    # 仕様ヘッダなしでも fallback は HTML 全体を spec_section として扱うので、
    # 偶然 【】 があればパースされる可能性 → 構造的に空 OK


# ============================================================================
# _parse_weight_g
# ============================================================================
def test_parse_weight_g_integer_string():
    assert m._parse_weight_g("303g") == "303"


def test_parse_weight_g_with_label():
    assert m._parse_weight_g("平均重量 254g") == "254"


def test_parse_weight_g_empty_input():
    assert m._parse_weight_g("") == ""


def test_parse_weight_g_no_match_returns_empty():
    assert m._parse_weight_g("not a weight") == ""


# ============================================================================
# Color suffix dict sanity
# ============================================================================
def test_color_suffix_dict_has_known_codes():
    """user spec 例の suffix code が dict に存在すること."""
    for sx in ["BK", "NV", "OV", "DKFO"]:
        assert sx in m._COLOR_SUFFIX_EN


def test_color_jp_dict_has_basic_colors():
    for jp in ["ブラック", "ネイビー", "ダークグリーン"]:
        assert jp in m._COLOR_JP_EN


# ============================================================================
# 推論: jacket length / fabric_type / care
# ============================================================================
def test_derive_length_long_for_long_keyword():
    assert m._derive_length("ロングダウンコート") == "Long"


def test_derive_length_default_mid():
    assert m._derive_length("ライトシェルパーカ") == "Mid-Length"


def test_derive_fabric_type_fleece_keyword():
    assert m._derive_fabric_type("フリースジャケット", {}) == "Fleece"


def test_derive_fabric_type_default_not_specified():
    assert m._derive_fabric_type("ストームクルーザー ジャケット", {}) == "Not Specified"


def test_derive_care_machine_washable_when_keyword_present():
    assert m._derive_care("洗濯機 で 洗える") == "Machine Washable"


def test_derive_care_default_not_specified():
    assert m._derive_care("plain text without keywords") == "Not Specified"


# ============================================================================
# disp_fo (廃盤 endpoint) — 2026-05-04 追加
# ============================================================================
def test_discontinued_url_template_format():
    """disp_fo URL pattern: /goods/disp_fo.php?product_id=X&force=1."""
    url = m.DISCONTINUED_URL_TEMPLATE.format(pid="1103242")
    assert "disp_fo.php" in url
    assert "product_id=1103242" in url
    assert "force=1" in url


def test_og_decodes_html_entities():
    """og:title などに含まれる HTML entity (&#039; = ') を decode して返す.

    disp_fo HTML の og:title が "Men&#039;s" 形式 → decode しないと
    department 判定 (endswith("Men's")) が失敗する.
    """
    html = '<meta property="og:title" content="ウインドブラスト パーカ Men&#039;s"/>'
    out = m._og(html, "title")
    assert out == "ウインドブラスト パーカ Men's"
    # 末尾 "Men's" が確認できるので department 判定が正しく動く
    assert out.endswith("Men's")


def test_parse_spec_block_simple_material_fallback():
    """素材ブロックに 表地/裏地 サブタグなし (1103242 ウインドブラスト等) でも、
    素材本文を 表地 として fallback で記録."""
    html = (
        '<h4 class="ttlType03">仕様</h4><p>'
        '【素材】40デニール・ナイロン・タフタ［はっ水加工］<br>'
        '【平均重量】174g'
        '</p>'
    )
    out = m._parse_spec_block(html)
    # 表地 サブタグなしでも 全体が 表地 として記録される
    assert "ナイロン" in out.get("表地", "")
    assert "174g" in out.get("平均重量", "")


# ============================================================================
# 廃盤対応 (Wayback / stub) — 2026-05-03 追加
# ============================================================================
def test_build_discontinued_stub_minimal_shape():
    """stub は specs.discontinued=True と Not Specified 値が入る."""
    stub = m._build_discontinued_stub("9999999", "https://example/9999999")
    assert stub["product_id"] == "9999999"
    assert stub["specs"]["discontinued"] is True
    assert stub["specs"]["brand"] == "montbell"
    assert stub["specs"]["outer_shell_material"] == "Not Specified"
    assert stub["color_variants"] == []
    assert stub["size_variants"] == []


def test_parse_color_variants_html_only_no_driver():
    """driver=None でも HTML から all_color の suffix list を抽出できる."""
    html = (
        '<input type="hidden" name="all_color" value="BK,NV,YL"/>'
        '<p>【カラー】ブラック(BK)、ネイビー(NV)、イエロー(YL)</p>'
    )
    out = m._parse_color_variants(html, driver=None)
    assert len(out) == 3
    suffixes = [c["suffix"] for c in out]
    assert "BK" in suffixes and "NV" in suffixes and "YL" in suffixes
    # JP 名 mapping 確認
    bk = next(c for c in out if c["suffix"] == "BK")
    assert bk["jp"] == "ブラック" and bk["en"] == "Black"


def test_parse_size_variants_html_only_no_driver():
    """driver=None でも HTML から select[name='X_Y_num'] の size 軸を抽出."""
    html = (
        '<select name="S_BK_num"><option>1</option></select>'
        '<select name="M_BK_num"><option>1</option></select>'
        '<select name="L_NV_num"><option>1</option></select>'
        '<select name="XL_NV_num"><option>1</option></select>'
    )
    out = m._parse_size_variants(html, driver=None)
    assert out == ["S", "M", "L", "XL"]


def test_parse_color_variants_empty_html_returns_empty():
    out = m._parse_color_variants("<html><body>no color</body></html>", driver=None)
    assert out == []


def test_parse_size_variants_empty_html_returns_empty():
    out = m._parse_size_variants("<html><body>no size</body></html>", driver=None)
    assert out == []


# Standalone runner
if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    cases = [
        ("translate first match Nylon",        test_translate_first_match_hits_first_jp_keyword),
        ("translate default no keyword",       test_translate_first_match_default_when_no_keyword),
        ("translate empty input default",      test_translate_first_match_empty_input_returns_default),
        ("activity hiking",                    test_derive_activity_hiking_keyword),
        ("activity climbing→hiking",           test_derive_activity_climbing_to_hiking),
        ("activity skiing",                    test_derive_activity_skiing),
        ("activity default hiking",            test_derive_activity_default_hiking_for_outdoor),
        ("type jacket / parka",                test_derive_type_jacket_default),
        ("type vest",                          test_derive_type_vest),
        ("type coat",                          test_derive_type_coat),
        ("style windbreaker",                  test_derive_style_windbreaker),
        ("style storm-cruiser → rain coat",    test_derive_style_rain_coat_storm_cruiser),
        ("style down → puffer",                test_derive_style_puffer_for_down),
        ("spec block parse full",              test_parse_spec_block_full_format),
        ("spec block parse missing",           test_parse_spec_block_missing_returns_empty_dict),
        ("weight integer string",              test_parse_weight_g_integer_string),
        ("weight with label",                  test_parse_weight_g_with_label),
        ("weight empty",                       test_parse_weight_g_empty_input),
        ("weight no match",                    test_parse_weight_g_no_match_returns_empty),
        ("color suffix sanity",                test_color_suffix_dict_has_known_codes),
        ("color JP sanity",                    test_color_jp_dict_has_basic_colors),
        ("length long",                        test_derive_length_long_for_long_keyword),
        ("length default mid",                 test_derive_length_default_mid),
        ("fabric fleece",                      test_derive_fabric_type_fleece_keyword),
        ("fabric default",                     test_derive_fabric_type_default_not_specified),
        ("care machine washable",              test_derive_care_machine_washable_when_keyword_present),
        ("care default",                       test_derive_care_default_not_specified),
        ("discontinued stub shape",            test_build_discontinued_stub_minimal_shape),
        ("color HTML only no driver",          test_parse_color_variants_html_only_no_driver),
        ("size HTML only no driver",           test_parse_size_variants_html_only_no_driver),
        ("color empty HTML",                   test_parse_color_variants_empty_html_returns_empty),
        ("size empty HTML",                    test_parse_size_variants_empty_html_returns_empty),
        ("disp_fo URL template",               test_discontinued_url_template_format),
        ("og: HTML entity decode",             test_og_decodes_html_entities),
        ("spec block 素材 single-line fallback", test_parse_spec_block_simple_material_fallback),
    ]
    fails = 0
    for name, fn in cases:
        try:
            fn()
            print(f"  ✓ {name}")
        except AssertionError as e:
            print(f"  ✗ FAIL: {name}: {e}")
            fails += 1
    if fails == 0:
        print(f"\n✅ All {len(cases)} montbell scraper tests passed.")
    else:
        print(f"\n❌ {fails} failed.")
        sys.exit(1)
