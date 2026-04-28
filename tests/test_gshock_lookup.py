#!/usr/bin/env python3
"""G-SHOCK catalog adapter テスト (Phase 3-A / 2026-04-29).

- `_generate_candidates` の表記揺れ正規化ロジックをユニットテスト
- `lookup_gshock` の None フォールバック挙動 (DB 未投入時の安全性)
- 実 DB への upsert + lookup roundtrip は Phase 3-C e2e で検証
"""
from __future__ import annotations
import sys
from pathlib import Path

# iMakCatalog/integrations を import path に追加
_REPO_ROOT = Path(__file__).resolve().parent.parent
_INTEGRATIONS = _REPO_ROOT / "iMakCatalog" / "integrations"
if str(_INTEGRATIONS) not in sys.path:
    sys.path.insert(0, str(_INTEGRATIONS))

from gshock_lookup import _generate_candidates, lookup_gshock  # noqa: E402


# ============================================================================
# _generate_candidates pure function tests
# ============================================================================
def test_jf_suffix_stripping():
    """JF suffix ありの型番は raw + suffix 剥がし版が候補に出る."""
    cands = _generate_candidates("GA-2100-1A1JF")
    assert "GA-2100-1A1JF" in cands
    assert "GA-2100-1A1" in cands


def test_jr_suffix_stripping():
    """JR suffix も同様に剥がす."""
    cands = _generate_candidates("DW-5600BB-1JR")
    assert "DW-5600BB-1JR" in cands
    assert "DW-5600BB-1" in cands


def test_no_suffix_returns_single_candidate():
    """suffix なし型番は1候補のみ (重複排除)."""
    cands = _generate_candidates("GA-2100-1A1")
    assert cands == ["GA-2100-1A1"]


def test_lowercase_to_uppercase():
    """小文字入力は大文字化候補が追加される."""
    cands = _generate_candidates("ga-2100-1a1")
    assert "ga-2100-1a1" in cands
    assert "GA-2100-1A1" in cands


def test_missing_prefix_hyphen():
    """prefix と数字の間のハイフンが欠落していたら補完される."""
    cands = _generate_candidates("GA2100-1A1")
    assert "GA2100-1A1" in cands
    assert "GA-2100-1A1" in cands


def test_existing_hyphens_not_destroyed():
    """正規入力 'GA-2100-1A1' を渡すと第2ハイフン以降が破壊されない (regression check)."""
    cands = _generate_candidates("GA-2100-1A1")
    # 'GA-21001A1' のような壊れた候補が含まれてはいけない (旧バグ)
    for c in cands:
        assert "21001A1" not in c, f"第2ハイフン破壊検出: {c!r}"


def test_empty_input_returns_empty_list():
    assert _generate_candidates("") == []
    assert _generate_candidates(None) == []  # type: ignore


def test_whitespace_input_stripped():
    cands = _generate_candidates("  GA-2100-1A1  ")
    assert "GA-2100-1A1" in cands


def test_long_prefix_4_letters():
    """4 文字 prefix (例: GMWB / MRGG / MTGB 系) も補正できる."""
    cands = _generate_candidates("GMWB5000D-1")
    assert "GMWB-5000D-1" in cands  # prefix-numeric ハイフン挿入


def test_candidates_no_duplicates():
    """同じ候補が重複して返らない."""
    cands = _generate_candidates("GA-2100-1A1")
    assert len(cands) == len(set(cands))


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
        ("JF suffix stripping",            test_jf_suffix_stripping),
        ("JR suffix stripping",            test_jr_suffix_stripping),
        ("no suffix → 1 candidate",        test_no_suffix_returns_single_candidate),
        ("lowercase → uppercase",          test_lowercase_to_uppercase),
        ("missing prefix hyphen",          test_missing_prefix_hyphen),
        ("existing hyphens preserved",     test_existing_hyphens_not_destroyed),
        ("empty input",                    test_empty_input_returns_empty_list),
        ("whitespace stripped",            test_whitespace_input_stripped),
        ("4-letter prefix",                test_long_prefix_4_letters),
        ("no duplicates",                  test_candidates_no_duplicates),
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
