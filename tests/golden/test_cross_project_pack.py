#!/usr/bin/env python3
"""Step 6.5: 4プロジェクト横断ゴールデンテストパック.

Gemini Round 4 「絶対防衛線」: 共通モジュール 1 行変更時に
全 4 プロジェクトのテストが pass しなければマージ禁止。

本テストは各プロジェクトの check_csv.py が読込む PROFIT_PARAMS を
凍結した期待値と比較する。yaml の category 名が変更されたり、
get_check_csv_params が壊れたら、4プロジェクト全てが赤になる。

将来追加予定:
- TCG/G-shock/Mercari/一番くじ それぞれの「代表 SKU 1件 → 期待 CSV」
  byte-level 比較 (要: 外部API凍結フィクスチャ)
"""
from __future__ import annotations
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent.parent
if str(_REPO / "iMakeBayAPI") not in sys.path:
    sys.path.insert(0, str(_REPO / "iMakeBayAPI"))

from profit_params import get_check_csv_params

try:
    import pytest
    _HAS_PYTEST = True
except ImportError:
    _HAS_PYTEST = False


# ===== 凍結した期待値 (yaml 2026-04-25-v1 時点) =====
# yaml が変更されたら期待値も更新（変更検知のための故意の硬さ）
EXPECTED_BY_PROJECT = {
    "iMakTCG":          {"category": "TCG(PSA10)", "fvf": 0.1325, "shipping_jpy": 2000},
    "iMakG-shock":      {"category": "G-SHOCK",    "fvf": 0.1325, "shipping_jpy": 2000},
    "iMakMercari":      {"category": "Tシャツ(UT)", "fvf": 0.153,  "shipping_jpy": 2000},
    "iMak_ichibankuji": {"category": "一番くじ",    "fvf": 0.1325, "shipping_jpy": 2500},
}


def _check_project(project_name: str, expected: dict) -> None:
    """指定プロジェクトの category で取得した PROFIT_PARAMS を検証"""
    params = get_check_csv_params(expected["category"])

    assert params["ebay_fee_rate"] == expected["fvf"], (
        f"{project_name} ({expected['category']}): "
        f"FVF expected {expected['fvf']}, got {params['ebay_fee_rate']}"
    )
    assert params["shipping_jpy"] == expected["shipping_jpy"], (
        f"{project_name} ({expected['category']}): "
        f"shipping_jpy expected {expected['shipping_jpy']}, got {params['shipping_jpy']}"
    )
    # 必須キー存在確認
    for key in ("exchange_rate", "promo_rate", "payo_rate"):
        assert key in params, f"{project_name}: missing key {key!r}"


def test_check_csv_loads_for_iMakTCG():
    _check_project("iMakTCG", EXPECTED_BY_PROJECT["iMakTCG"])


def test_check_csv_loads_for_iMakG_shock():
    _check_project("iMakG-shock", EXPECTED_BY_PROJECT["iMakG-shock"])


def test_check_csv_loads_for_iMakMercari():
    _check_project("iMakMercari", EXPECTED_BY_PROJECT["iMakMercari"])


def test_check_csv_loads_for_iMak_ichibankuji():
    _check_project("iMak_ichibankuji", EXPECTED_BY_PROJECT["iMak_ichibankuji"])


def test_unknown_category_raises():
    """未定義カテゴリは ValueError で弾く"""
    if _HAS_PYTEST:
        with pytest.raises(ValueError, match="Unknown category"):
            get_check_csv_params("NONEXISTENT-CATEGORY")
    else:
        try:
            get_check_csv_params("NONEXISTENT-CATEGORY")
            raise RuntimeError("Expected ValueError")
        except ValueError as e:
            assert "Unknown category" in str(e)


def test_all_4_projects_succeed_simultaneously():
    """4 プロジェクト全部の check_csv パスが同時に通ること = 横断的健全性"""
    failures = []
    for proj, expected in EXPECTED_BY_PROJECT.items():
        try:
            _check_project(proj, expected)
        except AssertionError as e:
            failures.append(f"  {proj}: {e}")
    assert not failures, "Cross-project failures:\n" + "\n".join(failures)


# Standalone runner
if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    cases = [
        ("iMakTCG",          test_check_csv_loads_for_iMakTCG),
        ("iMakG-shock",      test_check_csv_loads_for_iMakG_shock),
        ("iMakMercari",      test_check_csv_loads_for_iMakMercari),
        ("iMak_ichibankuji", test_check_csv_loads_for_iMak_ichibankuji),
        ("Unknown category", test_unknown_category_raises),
        ("4-project simultaneous", test_all_4_projects_succeed_simultaneously),
    ]
    fails = 0
    for name, fn in cases:
        try:
            fn()
            print(f"  ✓ {name}")
        except AssertionError as e:
            print(f"  ✗ FAIL: {name}\n      {e}")
            fails += 1
        except Exception as e:
            print(f"  ✗ ERROR: {name}\n      {type(e).__name__}: {e}")
            fails += 1
    print()
    if fails == 0:
        print(f"✅ All {len(cases)} cross-project tests passed.")
    else:
        print(f"❌ {fails}/{len(cases)} failed.")
        sys.exit(1)
