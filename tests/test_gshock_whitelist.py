"""gshock_whitelist.py 専用テスト (2026-05-05 専門化第 2 弾)

設計思想:
  共有 whitelist_registry.py から切出された G-shock 専用 whitelist の動作保証.
  共通モジュールに依存しないことを確認 + 主要シナリオの動作確認.

memory: category_specialization_principle.md / no_modification_chain.md
"""
import os
import sys

# iMakG-shock 配下を path に追加 (test_montbell_whitelist と同じ運用).
# import 後に path 除去で name shadowing 防止.
_GSHOCK = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "iMakG-shock"))
sys.path.insert(0, _GSHOCK)

from gshock_whitelist import (
    GSHOCK_WHITELIST,
    validate_and_normalize,
    build_retry_feedback,
)

while _GSHOCK in sys.path:
    sys.path.remove(_GSHOCK)


# ============================================================================
# データ完全性
# ============================================================================
def test_all_required_fields_present():
    """主要 22 フィールドが全て存在することを確認."""
    required = [
        "Brand", "Type", "Department", "Style", "Display", "Bezel Type",
        "Dial Pattern", "Band Material", "Case Material", "Features",
        "Movement", "Watch Shape", "Case Shape", "Band/Strap", "Closure",
        "Caseback", "Indices", "Customized", "Vintage", "Handmade",
        "With Original Box/Packaging", "With Papers",
    ]
    for field in required:
        assert field in GSHOCK_WHITELIST, f"必須フィールド '{field}' が GSHOCK_WHITELIST に存在しない"


def test_brand_values():
    """Brand: Casio / G-SHOCK / Baby-G の 3 値."""
    assert GSHOCK_WHITELIST["Brand"]["values"] == ["Casio", "G-SHOCK", "Baby-G"]
    assert GSHOCK_WHITELIST["Brand"]["strict"] is True


def test_features_is_multi():
    """Features は multi=True (カンマ区切り複数値)."""
    assert GSHOCK_WHITELIST["Features"].get("multi") is True


# ============================================================================
# normalize 動作
# ============================================================================
def test_movement_normalize_to_quartz():
    """Solar Quartz / Radio Controlled Quartz → Quartz."""
    norm, viol = validate_and_normalize({"Movement": "Solar Quartz"})
    assert norm["Movement"] == "Quartz"
    norm, _ = validate_and_normalize({"Movement": "Radio Controlled Quartz"})
    assert norm["Movement"] == "Quartz"


def test_style_sports_to_sport():
    """Style: Sports → Sport (eBay 公式は単数)."""
    norm, _ = validate_and_normalize({"Style": "Sports"})
    assert norm["Style"] == "Sport"


def test_band_material_carbon_fiber_to_resin():
    """Band Material: Carbon Fiber → Resin (eBay enum 外なので近似値)."""
    norm, _ = validate_and_normalize({"Band Material": "Carbon Fiber"})
    assert norm["Band Material"] == "Resin"


def test_features_normalize_shock_resist():
    """Features: Shock Resist → Shock-Resistant."""
    norm, _ = validate_and_normalize({"Features": "Shock Resist"})
    assert "Shock-Resistant" in norm["Features"]


def test_features_normalize_carbon_core_guard_dropped():
    """Features: Carbon Core Guard は eBay 非フィルタ値 → 空文字 → リストから削除."""
    norm, _ = validate_and_normalize({"Features": "Shock Resist, Carbon Core Guard, Tough Solar"})
    assert "Carbon Core Guard" not in norm["Features"]
    assert "Shock-Resistant" in norm["Features"]
    assert "Solar Powered" in norm["Features"]


# ============================================================================
# 違反検出
# ============================================================================
def test_brand_violation():
    """whitelist 外 Brand を検出."""
    norm, viol = validate_and_normalize({"Brand": "Patagonia"})
    assert len(viol) == 1
    assert viol[0][0] == "Brand"


def test_no_violation_for_valid_values():
    """全値正規値なら違反なし."""
    norm, viol = validate_and_normalize({
        "Brand": "Casio",
        "Type": "Wristwatch",
        "Department": "Men",
        "Movement": "Quartz",
        "Display": "Digital",
        "Watch Shape": "Round",
    })
    assert viol == [], f"全正規値で違反なしのはず: {viol}"


# ============================================================================
# build_retry_feedback
# ============================================================================
def test_build_retry_feedback_empty():
    assert build_retry_feedback([]) == ""


def test_build_retry_feedback_with_violations():
    fb = build_retry_feedback([
        ("Brand", "Patagonia", "有効値: ['Casio', ...]", "not_in_whitelist"),
    ])
    assert "Brand" in fb
    assert "Patagonia" in fb
    assert "not_in_whitelist" in fb


# ============================================================================
# 共通モジュール非依存性 (専門化の核)
# ============================================================================
def test_no_dependency_on_whitelist_registry():
    """gshock_whitelist が whitelist_registry に import 依存していないことを確認."""
    import gshock_whitelist
    src_path = gshock_whitelist.__file__
    with open(src_path, encoding="utf-8") as f:
        src = f.read()
    assert "from whitelist_registry" not in src, \
        "gshock_whitelist は whitelist_registry に import 依存してはならない (専門化原則)"
    assert "import whitelist_registry" not in src, \
        "gshock_whitelist は whitelist_registry に import 依存してはならない (専門化原則)"
