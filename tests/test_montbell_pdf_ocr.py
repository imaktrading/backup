#!/usr/bin/env python3
"""Phase: Montbell PDF OCR pipeline 純関数テスト (Claude API 呼出なし範囲).

検証対象:
  - _normalize_ocr_product: OCR JSON dict → catalog dict 整形
  - model_no validation (7-digit only)
  - JP→EN マッピング連携 (montbell.py の辞書再利用)
  - department / type / style 正規化
  - feature list / color variants の組立
"""
from __future__ import annotations
import sys
from pathlib import Path

# iMakCatalog/scrapers + iMakMercari path
_REPO_ROOT = Path(__file__).resolve().parent.parent
for p in (_REPO_ROOT / "iMakCatalog" / "scrapers",
          _REPO_ROOT / "iMakCatalog",
          _REPO_ROOT / "iMakMercari"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import montbell_pdf_ocr as ocr  # noqa: E402


# ============================================================================
# _normalize_ocr_product
# ============================================================================
def test_normalize_basic_product():
    """OCR から抽出した最小限の dict を catalog dict に正規化."""
    p = {
        "model_no": "1106645",
        "name_jp": "ライトシェルパーカ",
        "department": "Men's",
        "outer_shell_jp": "ナイロン",
        "lining_jp": "ポリエステル",
        "insulation_jp": None,
        "weight_g": "303",
        "price_jpy": "12430",
        "colors": [{"suffix": "BK", "jp": "ブラック"}],
        "sizes": ["S", "M", "L"],
        "features_jp": ["撥水", "軽量"],
        "description_jp": "シェル素材を使用したパーカ",
    }
    out = ocr._normalize_ocr_product(p, "test_catalog_2024")
    assert out is not None
    assert out["product_id"] == "1106645"
    assert out["name_jp"] == "ライトシェルパーカ"
    assert out["specs"]["outer_shell_material"] == "Nylon"
    assert out["specs"]["lining_material"] == "Polyester"
    assert out["specs"]["insulation_material"] == "Not Specified"
    assert out["specs"]["weight_g"] == "303"
    assert out["specs"]["retail_price_jpy"] == "12430"
    assert out["specs"]["department"] == "Men"
    assert out["specs"]["type"] == "Jacket"
    assert out["specs"]["style"] == "Parka"
    assert "Water Resistant" in out["specs"]["features"]
    assert "Lightweight" in out["specs"]["features"]
    assert out["specs"]["ocr_source"] == "test_catalog_2024"
    assert len(out["color_variants"]) == 1
    assert out["color_variants"][0]["en"] == "Black"
    assert out["size_variants"] == ["S", "M", "L"]


def test_normalize_rejects_non_7digit_model_no():
    """4-6 桁の model_no や英字混じりは reject."""
    for bad in ["12345", "ABCDEFG", "1234567A", "", "12345678"]:
        p = {"model_no": bad, "name_jp": "test"}
        out = ocr._normalize_ocr_product(p, "test")
        assert out is None, f"reject 失敗: {bad!r}"


def test_normalize_accepts_valid_7digit():
    p = {"model_no": "1234567", "name_jp": "test"}
    out = ocr._normalize_ocr_product(p, "test")
    assert out is not None and out["product_id"] == "1234567"


def test_normalize_womens_department():
    p = {"model_no": "1234567", "name_jp": "test", "department": "Women's"}
    out = ocr._normalize_ocr_product(p, "test")
    assert out["specs"]["department"] == "Women"


def test_normalize_unisex_department():
    p = {"model_no": "1234567", "name_jp": "test", "department": "Unisex"}
    out = ocr._normalize_ocr_product(p, "test")
    assert out["specs"]["department"] == "Unisex Adults"


def test_normalize_unknown_department_default():
    p = {"model_no": "1234567", "name_jp": "test", "department": ""}
    out = ocr._normalize_ocr_product(p, "test")
    assert out["specs"]["department"] == "Not Specified"


def test_normalize_handles_null_optional_fields():
    """OCR が null を返したフィールドを安全に Not Specified へ落とす."""
    p = {
        "model_no": "1234567",
        "name_jp": "test",
        "outer_shell_jp": None,
        "lining_jp": None,
        "insulation_jp": None,
        "weight_g": None,
        "price_jpy": None,
        "colors": None,
        "sizes": None,
        "features_jp": None,
    }
    out = ocr._normalize_ocr_product(p, "test")
    assert out["specs"]["outer_shell_material"] == "Not Specified"
    assert out["specs"]["weight_g"] == ""
    assert out["specs"]["retail_price_jpy"] == ""
    assert out["color_variants"] == []
    assert out["size_variants"] == []
    assert out["specs"]["features"] == []


def test_normalize_strips_comma_in_price():
    """価格に "12,430" のようにカンマ混入していても整数 string に."""
    p = {"model_no": "1234567", "name_jp": "t", "price_jpy": "12,430"}
    out = ocr._normalize_ocr_product(p, "test")
    assert out["specs"]["retail_price_jpy"] == "12430"


def test_normalize_strips_unit_in_weight():
    """重量に '303g' で渡されても整数 string に."""
    p = {"model_no": "1234567", "name_jp": "t", "weight_g": "303g"}
    out = ocr._normalize_ocr_product(p, "test")
    assert out["specs"]["weight_g"] == "303"


def test_normalize_color_with_unknown_suffix_falls_back_to_jp():
    """suffix 辞書未登録でも JP 色名から EN 推定."""
    p = {
        "model_no": "1234567",
        "name_jp": "test",
        "colors": [{"suffix": "ZZ", "jp": "ブラック"}],
    }
    out = ocr._normalize_ocr_product(p, "test")
    assert out["color_variants"][0]["en"] == "Black"


def test_normalize_color_unknown_returns_not_specified():
    p = {
        "model_no": "1234567",
        "name_jp": "test",
        "colors": [{"suffix": "ZZ", "jp": "謎の色"}],
    }
    out = ocr._normalize_ocr_product(p, "test")
    assert out["color_variants"][0]["en"] == "Not Specified"


def test_normalize_storm_cruiser_to_rain_coat():
    """商品名 'ストームクルーザー' → style='Rain Coat'."""
    p = {"model_no": "1234567", "name_jp": "ストームクルーザー ジャケット"}
    out = ocr._normalize_ocr_product(p, "test")
    assert out["specs"]["style"] == "Rain Coat"


def test_normalize_down_to_puffer():
    p = {"model_no": "1234567", "name_jp": "ライトダウンジャケット"}
    out = ocr._normalize_ocr_product(p, "test")
    assert out["specs"]["style"] == "Puffer Jacket"


def test_normalize_insulation_dictionary_match():
    """insulation_jp='ダウン' → insulation_material='Down'."""
    p = {"model_no": "1234567", "name_jp": "test", "insulation_jp": "ダウン"}
    out = ocr._normalize_ocr_product(p, "test")
    # _MATERIAL_JP_EN dict per montbell.py
    assert out["specs"]["insulation_material"] == "Down"


def test_normalize_features_jp_to_en():
    """機能 list の JP → EN 1st-stage 変換 + dedup."""
    p = {
        "model_no": "1234567",
        "name_jp": "test",
        "features_jp": ["撥水", "防水", "軽量", "防風"],
    }
    out = ocr._normalize_ocr_product(p, "test")
    feats = out["specs"]["features"]
    # Each JP keyword maps to EN.
    assert "Water Resistant" in feats
    assert "Waterproof" in feats
    assert "Lightweight" in feats
    assert "Windproof" in feats


# Standalone runner
if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    cases = [
        ("normalize basic product",                test_normalize_basic_product),
        ("reject non-7digit model_no",             test_normalize_rejects_non_7digit_model_no),
        ("accept valid 7digit",                    test_normalize_accepts_valid_7digit),
        ("Women's department",                     test_normalize_womens_department),
        ("Unisex department",                      test_normalize_unisex_department),
        ("unknown department default",             test_normalize_unknown_department_default),
        ("handles null optional fields",           test_normalize_handles_null_optional_fields),
        ("strips comma in price",                  test_normalize_strips_comma_in_price),
        ("strips unit in weight",                  test_normalize_strips_unit_in_weight),
        ("color unknown suffix → JP fallback",     test_normalize_color_with_unknown_suffix_falls_back_to_jp),
        ("color total unknown → Not Specified",    test_normalize_color_unknown_returns_not_specified),
        ("storm cruiser → Rain Coat",              test_normalize_storm_cruiser_to_rain_coat),
        ("down → Puffer Jacket",                   test_normalize_down_to_puffer),
        ("insulation Down dict match",             test_normalize_insulation_dictionary_match),
        ("features JP→EN multi",                   test_normalize_features_jp_to_en),
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
        print(f"\n✅ All {len(cases)} montbell PDF OCR tests passed.")
    else:
        print(f"\n❌ {fails} failed.")
        sys.exit(1)
