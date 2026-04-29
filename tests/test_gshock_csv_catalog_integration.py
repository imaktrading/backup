#!/usr/bin/env python3
"""Phase 3-B: gshock_to_csv ↔ iMakCatalog 連携の互換性テスト.

検証項目:
  1. gshock_to_csv の import が catalog 連携で壊れていない (module load smoke)
  2. catalog 未投入時の lookup → None フォールバック (既存挙動の保証)
  3. _catalog_record_to_scrape_dict が build_row に必要な全 key を返す
  4. band_strap_override の条件付き設定 (Two-Piece は省略 / Bracelet 等はセット)
  5. JF/JR suffix 剥がしによる model_base 派生

byte 互換 e2e (実 URL → CSV 行比較) は Phase 3-C 範疇のため本テストでは扱わない.
"""
from __future__ import annotations
import sys
from pathlib import Path

# 必要な path を通す.
# 注意 (2026-04-29 修正): import 後に iMakG-shock 系を sys.path から除去する.
# 残置すると後続テストの `import check_csv` が iMakG-shock/check_csv.py を pick し、
# Phase D 未適用版で test_phase_d_cache_sharing が偽陽性失敗する (name shadowing 事故).
_REPO_ROOT = Path(__file__).resolve().parent.parent
_GS_PATHS = [
    str(_REPO_ROOT / "iMakG-shock"),
    str(_REPO_ROOT / "iMakG-shock" / "casio_finder"),
]
_KEEP_PATHS = [
    str(_REPO_ROOT / "iMakeBayAPI"),
    str(_REPO_ROOT / "iMakCatalog" / "integrations"),
]
for p in _GS_PATHS + _KEEP_PATHS:
    if p not in sys.path:
        sys.path.insert(0, p)

import gshock_to_csv  # noqa: E402

# import 完了後、iMakG-shock 系の path を除去 (name shadowing 防止).
# gshock_to_csv は sys.modules にキャッシュ済なので、以後の参照は path 不要.
for p in _GS_PATHS:
    while p in sys.path:
        sys.path.remove(p)


# ============================================================================
# 1. module load smoke test
# ============================================================================
def test_module_imports_with_catalog_adapter():
    """gshock_to_csv が catalog adapter を含む状態で import できること."""
    # _catalog_lookup は callable (iMakCatalog 配置あり) または None (フォールバック) のいずれか
    assert hasattr(gshock_to_csv, "_catalog_lookup")
    assert gshock_to_csv._catalog_lookup is None or callable(gshock_to_csv._catalog_lookup)


def test_catalog_helper_exists():
    """_catalog_record_to_scrape_dict が定義されていて callable."""
    assert callable(gshock_to_csv._catalog_record_to_scrape_dict)


# ============================================================================
# 2. catalog miss フォールバック (既存挙動の保証 = byte 互換の前提)
# ============================================================================
def test_catalog_miss_returns_none():
    """DB に未投入の型番で lookup → None (例外なし)."""
    if gshock_to_csv._catalog_lookup is None:
        # catalog adapter 未配置の環境: フォールバック自体が完璧 (lookup を呼ばない)
        return
    result = gshock_to_csv._catalog_lookup("GA-9999-XXXX-NOT-EXIST")
    assert result is None


# ============================================================================
# 3. _catalog_record_to_scrape_dict の shape 検証
# ============================================================================
_BUILD_ROW_REQUIRED_KEYS = {
    # build_row が data.get() で参照する全 key (band_strap_override は条件付き)
    "model", "model_base", "model_official",
    "case_size", "case_thickness", "case_material", "case_shape",
    "band_material", "band_width", "band_length", "band_color",
    "dial_color", "bezel_color",
    "crystal", "movement", "water_resistance",
    "weight", "year", "display", "features", "is_metal",
}


def _make_fake_catalog_record(band_strap="Two-Piece Strap", is_metal=False,
                               product_id="GA-2100-1A1JF"):
    """catalog 互換 record 雛形."""
    return {
        "product_id": product_id,
        "specs": {
            "case_size": "45.4 mm", "case_thickness": "11.8 mm",
            "case_material": "Resin", "case_shape": "Round",
            "band_material": "Resin", "band_width": "16 mm",
            "band_length": "165-220 mm",
            "band_color": "Black", "band_strap": band_strap,
            "dial_color": "Black", "bezel_color": "Black",
            "crystal": "Mineral Crystal", "movement": "Quartz",
            "water_resistance": "200 m (20 ATM)",
            "weight": "52 g", "year": "2019",
            "display": "Analog", "features": "Shock-Resistant",
            "is_metal": is_metal,
        },
    }


def test_returned_dict_has_all_build_row_required_keys():
    """_catalog_record_to_scrape_dict が build_row 必須 key を全部含む."""
    record = _make_fake_catalog_record()
    data = gshock_to_csv._catalog_record_to_scrape_dict(record, "GA-2100-1A1JF")
    missing = _BUILD_ROW_REQUIRED_KEYS - data.keys()
    assert not missing, f"build_row 必須 key 欠落: {missing}"


def test_model_base_strips_jf_suffix():
    """model_base から JF suffix が剥がれている."""
    record = _make_fake_catalog_record(product_id="GA-2100-1A1JF")
    data = gshock_to_csv._catalog_record_to_scrape_dict(record, "GA-2100-1A1JF")
    assert data["model_official"] == "GA-2100-1A1JF"
    assert data["model_base"] == "GA-2100-1A1"


def test_model_base_strips_jr_suffix():
    record = _make_fake_catalog_record(product_id="DW-5600BB-1JR")
    data = gshock_to_csv._catalog_record_to_scrape_dict(record, "DW-5600BB-1JR")
    assert data["model_base"] == "DW-5600BB-1"


def test_model_base_unchanged_without_suffix():
    record = _make_fake_catalog_record(product_id="GA-2100-1A1")
    data = gshock_to_csv._catalog_record_to_scrape_dict(record, "GA-2100-1A1")
    assert data["model_base"] == "GA-2100-1A1"


# ============================================================================
# 4. band_strap_override の条件付き設定 (scrape_casio 互換)
# ============================================================================
def test_two_piece_strap_omits_override():
    """band_strap='Two-Piece Strap' のとき band_strap_override は dict に含まない.

    (build_row の data.get('band_strap_override', 'Two-Piece Strap') の default
     が発動するように、scrape_casio 側の挙動と揃える)
    """
    record = _make_fake_catalog_record(band_strap="Two-Piece Strap")
    data = gshock_to_csv._catalog_record_to_scrape_dict(record, "GA-2100-1A1JF")
    assert "band_strap_override" not in data


def test_bracelet_sets_override():
    """band_strap='Bracelet' (GMW/MRGG/MTG 系) のときは override key をセット."""
    record = _make_fake_catalog_record(band_strap="Bracelet", is_metal=True,
                                        product_id="GMW-B5000D-1JF")
    data = gshock_to_csv._catalog_record_to_scrape_dict(record,
                                                         "GMW-B5000D-1JF")
    assert data.get("band_strap_override") == "Bracelet"


def test_empty_band_strap_omits_override():
    """band_strap が空文字 / None のときも override 立てない."""
    record = _make_fake_catalog_record(band_strap="")
    data = gshock_to_csv._catalog_record_to_scrape_dict(record, "GA-2100-1A1JF")
    assert "band_strap_override" not in data


# ============================================================================
# 5. None / 不正入力のフォールバック
# ============================================================================
def test_none_record_returns_none():
    assert gshock_to_csv._catalog_record_to_scrape_dict(None, "GA-2100-1A1JF") is None


def test_record_without_specs_uses_empty():
    """specs が無い record でも crash せず default 値で埋まる."""
    record = {"product_id": "GA-2100-1A1JF"}  # specs 欠落
    data = gshock_to_csv._catalog_record_to_scrape_dict(record, "GA-2100-1A1JF")
    assert data is not None
    assert data["case_size"] == ""
    assert data["is_metal"] is False


# Standalone runner
if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    cases = [
        ("module imports with catalog adapter", test_module_imports_with_catalog_adapter),
        ("catalog helper exists",                test_catalog_helper_exists),
        ("catalog miss returns None",            test_catalog_miss_returns_none),
        ("dict has all build_row keys",          test_returned_dict_has_all_build_row_required_keys),
        ("model_base strips JF",                 test_model_base_strips_jf_suffix),
        ("model_base strips JR",                 test_model_base_strips_jr_suffix),
        ("model_base unchanged no suffix",       test_model_base_unchanged_without_suffix),
        ("Two-Piece omits override",             test_two_piece_strap_omits_override),
        ("Bracelet sets override",               test_bracelet_sets_override),
        ("empty band_strap omits override",      test_empty_band_strap_omits_override),
        ("None record → None",                   test_none_record_returns_none),
        ("record w/o specs uses defaults",       test_record_without_specs_uses_empty),
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
        print(f"\n✅ All {len(cases)} gshock_to_csv catalog integration tests passed.")
    else:
        print(f"\n❌ {fails} failed.")
        sys.exit(1)
