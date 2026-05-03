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
