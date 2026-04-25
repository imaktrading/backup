#!/usr/bin/env python3
"""iMak Trading Japan - Golden Test 足場検証.

本ファイルは Step 4-B の足場検証テスト。
将来、PSA cert -> CSV のフルゴールデンテストはこの上に乗せる。

検証内容:
  - normalize_csv が改行/列順/数値の差異を吸収できるか
  - assert_csv_logical_equal が論理一致を正しく判定するか
  - 論理的に異なる CSV を正しく拒否するか
"""
from __future__ import annotations
import sys
from pathlib import Path

# tests/ を import path に追加
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tests.helpers.normalizer import normalize_csv, assert_csv_logical_equal

try:
    import pytest
    _HAS_PYTEST = True
except ImportError:
    _HAS_PYTEST = False


# ===== fixtures =====
CSV_BASE = (
    "Title,Price,Stock\n"
    "Item A,1.0,5\n"
    "Item B,2.50,10\n"
)

# 改行コードだけ違う (CRLF)
CSV_DIFF_NEWLINE = (
    "Title,Price,Stock\r\n"
    "Item A,1.0,5\r\n"
    "Item B,2.50,10\r\n"
)

# 列順だけ違う (Stock, Title, Price)
CSV_DIFF_COL_ORDER = (
    "Stock,Title,Price\n"
    "5,Item A,1.0\n"
    "10,Item B,2.50\n"
)

# 数値表現だけ違う (1.0 -> 1, 2.50 -> 2.5)
CSV_DIFF_NUMERIC = (
    "Title,Price,Stock\n"
    "Item A,1,5\n"
    "Item B,2.5,10\n"
)

# セル前後の空白だけ違う
CSV_DIFF_WHITESPACE = (
    "Title,Price,Stock\n"
    " Item A , 1.0 , 5 \n"
    "  Item B  ,  2.50  ,  10  \n"
)

# 全部混合: 改行+列順+数値+空白
CSV_DIFF_ALL = (
    "Stock,Title,Price\r\n"
    " 5 , Item A , 1 \r\n"
    " 10 , Item B , 2.5 \r\n"
)

# 論理的に異なる (価格が違う)
CSV_REALLY_DIFFERENT = (
    "Title,Price,Stock\n"
    "Item A,1.0,5\n"
    "Item B,99.99,10\n"   # ← 本物の差異
)


# ===== test cases =====
def test_normalize_absorbs_newline_diff():
    """改行コード差異を吸収"""
    assert_csv_logical_equal(CSV_DIFF_NEWLINE, CSV_BASE)


def test_normalize_absorbs_column_order_diff():
    """列順差異を吸収"""
    assert_csv_logical_equal(CSV_DIFF_COL_ORDER, CSV_BASE)


def test_normalize_absorbs_numeric_format_diff():
    """数値フォーマット差異 (1.0 vs 1, 2.50 vs 2.5) を吸収"""
    assert_csv_logical_equal(CSV_DIFF_NUMERIC, CSV_BASE)


def test_normalize_absorbs_whitespace_diff():
    """セル前後の空白差異を吸収"""
    assert_csv_logical_equal(CSV_DIFF_WHITESPACE, CSV_BASE)


def test_normalize_absorbs_all_combined_diff():
    """改行+列順+数値+空白の全部混合を吸収"""
    assert_csv_logical_equal(CSV_DIFF_ALL, CSV_BASE)


def test_normalize_rejects_real_difference():
    """本当に違う内容 (価格が違う) は不一致として検出"""
    if _HAS_PYTEST:
        with pytest.raises(AssertionError, match="logical mismatch"):
            assert_csv_logical_equal(CSV_REALLY_DIFFERENT, CSV_BASE)
    else:
        try:
            assert_csv_logical_equal(CSV_REALLY_DIFFERENT, CSV_BASE)
            raise RuntimeError("Expected AssertionError but none raised")
        except AssertionError as e:
            assert "logical mismatch" in str(e)


def test_normalize_idempotent():
    """正規化を2回適用しても結果が変わらない"""
    once = normalize_csv(CSV_DIFF_ALL)
    twice = normalize_csv(once)
    assert once == twice


def test_normalize_empty_input():
    """空入力で例外を出さない"""
    assert normalize_csv("") == ""


# ===== standalone runner (pytest なし環境向け) =====
if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    cases = [
        ("newline diff",           test_normalize_absorbs_newline_diff),
        ("column order diff",      test_normalize_absorbs_column_order_diff),
        ("numeric format diff",    test_normalize_absorbs_numeric_format_diff),
        ("whitespace diff",        test_normalize_absorbs_whitespace_diff),
        ("all combined diff",      test_normalize_absorbs_all_combined_diff),
        ("rejects real difference", test_normalize_rejects_real_difference),
        ("idempotent",             test_normalize_idempotent),
        ("empty input",            test_normalize_empty_input),
    ]
    failed = 0
    for name, fn in cases:
        try:
            fn()
            print(f"  ✓ {name}")
        except AssertionError as e:
            print(f"  ✗ FAIL: {name}\n      {e}")
            failed += 1
        except Exception as e:
            print(f"  ✗ ERROR: {name}\n      {type(e).__name__}: {e}")
            failed += 1
    print()
    if failed == 0:
        print(f"✅ All {len(cases)} golden test scaffolding cases passed.")
        sys.exit(0)
    else:
        print(f"❌ {failed}/{len(cases)} failed.")
        sys.exit(1)
