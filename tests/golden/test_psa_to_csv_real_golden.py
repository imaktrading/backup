#!/usr/bin/env python3
"""Step 4 真の本番: 実弾フィクスチャによる byte 一致 golden test.

Gemini 最終指令:
> 過去に成功した本物の「PSA / Bandai / eBay レスポンス JSON」を特定し、
> tests/golden/fixtures/ に保存。その入力から生成される CSV を「絶対正解」として固定し、
> 正規化後の byte 単位での一致をパス。

検証フロー:
    [golden_input_001.json (PSA + Bandai + 凍結 schedule)]
              ↓
    [build_listing_row → row_to_csv_string]
              ↓
    [normalize_csv で正規化]
              ↓
    [golden_output_001.csv (絶対正解) と byte 一致比較]

このテストが赤になる = build_listing_row のロジックか yaml(SSOT) の値が
過去の成功と 1bit でも狂った = 即刻 commit ブロック。
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent.parent
if str(_REPO / "iMakeBayAPI") not in sys.path:
    sys.path.insert(0, str(_REPO / "iMakeBayAPI"))
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from listing_row_builder import build_listing_row, row_to_csv_string  # noqa: E402
from tests.helpers.normalizer import normalize_csv, assert_csv_logical_equal  # noqa: E402


FIXTURES = _REPO / "tests" / "golden" / "fixtures"
INPUT_001  = FIXTURES / "golden_input_001.json"
OUTPUT_001 = FIXTURES / "golden_output_001.csv"


def _run_001():
    """凍結入力から CSV 文字列を生成して返す"""
    with INPUT_001.open(encoding="utf-8") as f:
        inp = json.load(f)
    row = build_listing_row(inp)
    return row_to_csv_string(row)


def test_golden_001_byte_exact_match():
    """正規化なし、byte 完全一致 (改行・列順・数値表記まで含めて 1bit も狂わない)"""
    actual = _run_001()
    expected = OUTPUT_001.read_text(encoding="utf-8")
    assert actual == expected, (
        f"BYTE MISMATCH\n"
        f"  actual length:   {len(actual)}\n"
        f"  expected length: {len(expected)}\n"
        f"  --- first 200 actual:   {actual[:200]!r}\n"
        f"  --- first 200 expected: {expected[:200]!r}"
    )


def test_golden_001_logical_match_via_normalizer():
    """正規化経由でも一致 (改行差異等を吸収しても結論変わらず)"""
    actual = _run_001()
    expected = OUTPUT_001.read_text(encoding="utf-8")
    assert_csv_logical_equal(actual, expected)


def test_golden_001_idempotent():
    """build_listing_row が同入力 → 完全に同じ出力 (再現性 100%)"""
    out1 = _run_001()
    out2 = _run_001()
    out3 = _run_001()
    assert out1 == out2 == out3, "build_listing_row must be deterministic"


def test_golden_001_critical_fields_present():
    """致命的に必要なフィールドが揃っていること（SNAD / 出品エラー防止）"""
    with INPUT_001.open(encoding="utf-8") as f:
        inp = json.load(f)
    row = build_listing_row(inp)
    # eBay 必須
    assert row["*Title"], "Title must not be empty"
    assert row["*Category"], "Category must not be empty"
    assert row["*StartPrice"], "StartPrice must not be empty"
    assert row["ConditionID"], "ConditionID must not be empty"
    # PSA 鑑定情報
    assert row["CDA:Certification Number - (ID: 27503)"], "PSA cert number missing"
    assert row["C:Grade"], "Grade missing"
    # CLAUDE.md 規約: Country of Origin は空欄禁止
    assert row["C:Country of Origin"] == "Does not apply"
    # Mfr (TCG)
    assert row["C:Manufacturer"] == "Bandai"


def test_no_jp_chars_in_system_columns():
    """システム列に日本語混入無し（cp932 文字化け事故防止）"""
    with INPUT_001.open(encoding="utf-8") as f:
        inp = json.load(f)
    row = build_listing_row(inp)
    SYSTEM_COLS = ["*Format", "*Duration", "*Quantity", "ConditionID",
                   "BestOfferEnabled", "C:Country of Origin"]
    for col in SYSTEM_COLS:
        val = row[col]
        for ch in val:
            assert ord(ch) < 0x3000, f"{col}={val!r} contains JP char {ch!r}"


# Standalone runner
if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    cases = [
        ("byte exact match",                 test_golden_001_byte_exact_match),
        ("logical match via normalizer",     test_golden_001_logical_match_via_normalizer),
        ("idempotent (deterministic)",       test_golden_001_idempotent),
        ("critical fields present",          test_golden_001_critical_fields_present),
        ("no JP in system columns",          test_no_jp_chars_in_system_columns),
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
        print(f"✅ All {len(cases)} REAL GOLDEN tests passed (byte一致達成).")
    else:
        print(f"❌ {fails}/{len(cases)} failed.")
        sys.exit(1)
