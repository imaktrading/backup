#!/usr/bin/env python3
"""G-SHOCK catalog adapter テスト (Phase 3-A / 2026-04-29 → 2026-06-11 fail-closed 改訂).

- `_normalize_forms` の表記揺れ正規化 (大文字化 / ハイフン補正) をユニットテスト
- `_split_region` の region suffix 分離 (J 始まりのみ、末尾 A は色) をテスト
- `lookup_gshock` の None フォールバック挙動 (DB 未投入時の安全性)
- fail-closed 規約 (suffix exact / bare-with-twin→None / bare-only→hit) は
  iMakCatalog/tests/test_gshock_lookup_failclosed.py で実 DB 検証
"""
from __future__ import annotations
import sys
from pathlib import Path

# iMakCatalog/integrations を import path に追加
_REPO_ROOT = Path(__file__).resolve().parent.parent
_INTEGRATIONS = _REPO_ROOT / "iMakCatalog" / "integrations"
if str(_INTEGRATIONS) not in sys.path:
    sys.path.insert(0, str(_INTEGRATIONS))

from gshock_lookup import _normalize_forms, _split_region, lookup_gshock  # noqa: E402


# ============================================================================
# _normalize_forms / _split_region pure function tests
# ============================================================================
def test_jf_suffix_preserved():
    """canonical=suffix込み のため JF は剥がさず保持する (旧仕様の逆)."""
    forms = _normalize_forms("GA-2100-1A1JF")
    assert "GA-2100-1A1JF" in forms
    assert all(f.endswith("JF") for f in forms)  # bare 形は生成しない
    # region 分離は _split_region 側の責務
    assert _split_region("GA-2100-1A1JF") == ("GA-2100-1A1", "JF")


def test_jr_suffix_preserved():
    forms = _normalize_forms("DW-5600BB-1JR")
    assert "DW-5600BB-1JR" in forms
    assert _split_region("DW-5600BB-1JR") == ("DW-5600BB-1", "JR")


def test_ajf_keeps_color_A():
    """末尾 A は色コード → region は JF、base は ...A を保持 (AJF≠地域)."""
    assert _split_region("GBX-100-2AJF") == ("GBX-100-2A", "JF")


def test_no_suffix_returns_single_form():
    """suffix/補正なし型番は1形のみ (重複排除)."""
    assert _normalize_forms("GA-2100-1A1") == ["GA-2100-1A1"]
    assert _split_region("GA-2100-1A1") == ("GA-2100-1A1", None)


def test_lowercase_to_uppercase():
    """小文字入力は大文字化される."""
    forms = _normalize_forms("ga-2100-1a1")
    assert "GA-2100-1A1" in forms


def test_missing_prefix_hyphen():
    """prefix と数字の間のハイフンが欠落していたら補完される."""
    forms = _normalize_forms("GA2100-1A1")
    assert "GA2100-1A1" in forms
    assert "GA-2100-1A1" in forms


def test_existing_hyphens_not_destroyed():
    """正規入力 'GA-2100-1A1' を渡すと第2ハイフン以降が破壊されない (regression check)."""
    for c in _normalize_forms("GA-2100-1A1"):
        assert "21001A1" not in c, f"第2ハイフン破壊検出: {c!r}"


def test_empty_input_returns_empty_list():
    assert _normalize_forms("") == []
    assert _normalize_forms(None) == []  # type: ignore


def test_whitespace_input_stripped():
    assert "GA-2100-1A1" in _normalize_forms("  GA-2100-1A1  ")


def test_long_prefix_4_letters():
    """4 文字 prefix (例: GMWB / MRGG / MTGB 系) も補正できる."""
    assert "GMWB-5000D-1" in _normalize_forms("GMWB5000D-1")


def test_internal_space_to_hyphen():
    """型番内スペース (title 由来) をハイフン形で吸収."""
    assert "GA-2100-1A1" in _normalize_forms("GA 2100-1A1")


def test_internal_space_prefix_number():
    """'DW 5600' (prefix と番号の間スペース) → 'DW-5600' 形を生成."""
    assert "DW-5600" in _normalize_forms("DW 5600")


def test_forms_no_duplicates():
    """同じ形が重複して返らない."""
    forms = _normalize_forms("GA-2100-1A1")
    assert len(forms) == len(set(forms))


# ============================================================================
# lookup_gshock smoke tests (DB 未投入時の挙動)
# ============================================================================
def test_lookup_returns_none_for_unknown_model():
    """DB 未登録の型番は None 返却 (例外を投げない)."""
    # Phase 3-A 時点では G-SHOCK record はまだ投入されていないので必ず None になる想定
    result = lookup_gshock("GA-9999-XXXX")
    assert result is None


def test_lookup_returns_none_for_empty_input():
    assert lookup_gshock("") is None
    assert lookup_gshock(None) is None  # type: ignore


def test_lookup_does_not_crash_on_special_chars():
    """ハイフン以外の特殊文字が混入しても例外にならず None で済む."""
    # 危険入力: SQL インジェクション類, 改行, スラッシュ
    safe = ["GA' OR 1=1--", "GA\n2100", "GA/2100"]
    for s in safe:
        # api.lookup は parameterized query なので SQLi 不可だが念のため smoke
        result = lookup_gshock(s)
        assert result is None or isinstance(result, dict)


# Standalone runner
if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    cases = [
        ("JF suffix preserved",            test_jf_suffix_preserved),
        ("JR suffix preserved",            test_jr_suffix_preserved),
        ("AJF keeps color A",              test_ajf_keeps_color_A),
        ("no suffix → 1 form",             test_no_suffix_returns_single_form),
        ("lowercase → uppercase",          test_lowercase_to_uppercase),
        ("missing prefix hyphen",          test_missing_prefix_hyphen),
        ("existing hyphens preserved",     test_existing_hyphens_not_destroyed),
        ("empty input",                    test_empty_input_returns_empty_list),
        ("whitespace stripped",            test_whitespace_input_stripped),
        ("4-letter prefix",                test_long_prefix_4_letters),
        ("no duplicates",                  test_forms_no_duplicates),
        ("unknown model → None",           test_lookup_returns_none_for_unknown_model),
        ("empty input lookup → None",      test_lookup_returns_none_for_empty_input),
        ("special chars safety",           test_lookup_does_not_crash_on_special_chars),
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
        print(f"\n✅ All {len(cases)} gshock_lookup tests passed.")
    else:
        print(f"\n❌ {fails} failed.")
        sys.exit(1)
