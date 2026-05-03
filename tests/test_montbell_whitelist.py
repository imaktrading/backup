"""montbell_whitelist.py 専用テスト (2026-05-03 専門化に伴い新規作成)

設計思想:
  共有 whitelist_registry.py から切出された Montbell 専用 whitelist の動作保証。
  共通モジュールに依存しないことを確認 + 主要シナリオの動作確認。

専門化の弊害対策 C として追加 (memory: category_specialization_principle.md)。
"""
import os
import sys

# iMakMercari 配下を path に追加.
# 注意 (2026-05-03): import 後に sys.path から除去する (test_gshock_csv_catalog_integration と同じ運用).
# 残置すると後続テスト (test_phase_d_cache_sharing) の `import check_csv` が
# iMakMercari/check_csv.py (Phase D 未適用版、main() 引数なし) を pick して偽陽性失敗する.
_MERCARI = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "iMakMercari"))
sys.path.insert(0, _MERCARI)

from montbell_whitelist import (
    MONTBELL_WHITELIST,
    validate_and_normalize,
    build_retry_feedback,
)

# import 完了後、iMakMercari を sys.path から除去 (name shadowing 防止).
# montbell_whitelist は sys.modules にキャッシュ済、以後 path 不要.
while _MERCARI in sys.path:
    sys.path.remove(_MERCARI)


# ============================================================================
# データ完全性
# ============================================================================
def test_all_required_fields_present():
    """主要 21 フィールドが全て存在することを確認."""
    required = [
        "Brand", "Type", "Style", "Outer Shell Material", "Lining Material",
        "Insulation Material", "Fabric Type", "Closure", "Performance/Activity",
        "Pattern", "Department", "Size Type", "Size", "Color", "Theme",
        "Occasion", "Features", "Fit", "Accents",
        "Country/Region of Manufacture", "Jacket/Coat Length", "Garment Care",
        "Vintage", "Handmade",
    ]
    for field in required:
        assert field in MONTBELL_WHITELIST, f"必須フィールド '{field}' が MONTBELL_WHITELIST に存在しない"


def test_not_specified_in_filter_fields():
    """eBay フィルタに 'Not Specified' が存在するフィールドで whitelist にも含まれていることを確認."""
    fields_with_not_specified = [
        "Style", "Outer Shell Material", "Lining Material", "Insulation Material",
        "Fabric Type", "Performance/Activity", "Pattern", "Department",
        "Size Type", "Color", "Occasion", "Accents",
        "Country/Region of Manufacture", "Jacket/Coat Length", "Garment Care",
        "Handmade",
    ]
    for field in fields_with_not_specified:
        assert "Not Specified" in MONTBELL_WHITELIST[field]["values"], \
            f"'{field}' の values に 'Not Specified' が無い (eBay 公式値)"


# ============================================================================
# normalize 動作
# ============================================================================
def test_does_not_apply_normalized_to_not_specified():
    """旧デフォルト 'Does not apply' が 'Not Specified' に正規化される."""
    norm, viol = validate_and_normalize({
        "Insulation Material": "Does not apply",
        "Lining Material": "Does not apply",
        "Outer Shell Material": "Does not apply",
    })
    assert norm["Insulation Material"] == "Not Specified"
    assert norm["Lining Material"] == "Not Specified"
    assert norm["Outer Shell Material"] == "Not Specified"
    assert viol == [], "正規化成功なので違反なし"


def test_fabric_type_nylon_normalized():
    """Fabric Type に Nylon (素材、織り方ではない) が来たら Not Specified に正規化."""
    norm, viol = validate_and_normalize({"Fabric Type": "Nylon"})
    assert norm["Fabric Type"] == "Not Specified"
    assert viol == []


def test_brand_normalize():
    """Brand バリエーションが montbell に正規化."""
    for variant in ["MONTBELL", "Montbell", "Mont Bell"]:
        norm, viol = validate_and_normalize({"Brand": variant})
        assert norm["Brand"] == "montbell", f"'{variant}' → 'montbell' に正規化されるべき"


def test_color_olive_normalize():
    """Color: Olive → Green 正規化."""
    norm, _ = validate_and_normalize({"Color": "Olive"})
    assert norm["Color"] == "Green"


# ============================================================================
# 違反検出
# ============================================================================
def test_brand_violation():
    """whitelist 外の Brand を検出."""
    norm, viol = validate_and_normalize({"Brand": "Patagonia"})
    assert len(viol) == 1
    assert viol[0][0] == "Brand"


def test_no_violation_for_valid_values():
    """全値正規値なら違反なし."""
    norm, viol = validate_and_normalize({
        "Brand": "montbell",
        "Type": "Jacket",
        "Style": "Windbreaker",
        "Outer Shell Material": "Nylon",
        "Insulation Material": "Not Specified",
        "Fabric Type": "Softshell",
        "Color": "Green",
    })
    assert viol == [], f"全正規値で違反なしのはず: {viol}"


# ============================================================================
# multi=True 動作
# ============================================================================
def test_performance_activity_multi():
    """Performance/Activity (multi=True) のカンマ区切り検証."""
    norm, _ = validate_and_normalize({
        "Performance/Activity": "Hiking, Outdoor, Camping"
    })
    # Outdoor / Camping → Hiking に正規化、重複排除
    assert "Hiking" in norm["Performance/Activity"]


# ============================================================================
# build_retry_feedback
# ============================================================================
def test_build_retry_feedback_empty():
    assert build_retry_feedback([]) == ""


def test_build_retry_feedback_with_violations():
    fb = build_retry_feedback([
        ("Brand", "Patagonia", "有効値: ['montbell', ...]", "not_in_whitelist"),
    ])
    assert "Brand" in fb
    assert "Patagonia" in fb
    assert "not_in_whitelist" in fb


# ============================================================================
# 共通モジュール非依存性 (専門化の核)
# ============================================================================
def test_no_dependency_on_whitelist_registry():
    """montbell_whitelist が whitelist_registry に import 依存していないことを確認."""
    import montbell_whitelist
    src_path = montbell_whitelist.__file__
    with open(src_path, encoding="utf-8") as f:
        src = f.read()
    # whitelist_registry を import していないこと
    assert "from whitelist_registry" not in src, \
        "montbell_whitelist は whitelist_registry に import 依存してはならない (専門化原則)"
    assert "import whitelist_registry" not in src, \
        "montbell_whitelist は whitelist_registry に import 依存してはならない (専門化原則)"
