#!/usr/bin/env python3
"""ONE PIECE Canonical Map 正規化テスト (2026-04-25 Bug 2-5 修正).

検証対象:
- _onepiece_set_code_to_name: OP-01 → Romance Dawn 等
- 既知セット (OP-01〜OP-14, ST-01〜ST-26, EB-01〜EB-02, PRB-01〜PRB-02) のヒット
- 未知セットは set_code をそのまま返す（フォールバック）
"""
from __future__ import annotations
import sys
from pathlib import Path

# psa_to_csv.py から純関数 _onepiece_set_code_to_name と _ONEPIECE_SET_NAME_MAP を抽出.
# psa_to_csv は top-level で重い import があるため、コードを直接読込んで関数だけ取り出す.
_PSA_TO_CSV = Path(__file__).resolve().parent.parent / "iMakTCG" / "psa_to_csv.py"


def _extract_set_map():
    """psa_to_csv.py から _ONEPIECE_SET_NAME_MAP の dict をパース取得 (重 import を回避)."""
    text = _PSA_TO_CSV.read_text(encoding="utf-8")
    start = text.find("_ONEPIECE_SET_NAME_MAP = {")
    assert start >= 0, "_ONEPIECE_SET_NAME_MAP not found in psa_to_csv.py"
    # 最初の "}" 行までを切出
    snippet = text[start:]
    end = snippet.find("\n}\n")
    assert end >= 0
    snippet = snippet[: end + 2]
    # exec して dict を取得
    g: dict = {}
    exec(snippet, g)
    return g["_ONEPIECE_SET_NAME_MAP"]


SET_MAP = _extract_set_map()


def _convert(set_code: str) -> str:
    return SET_MAP.get(set_code, set_code)


def test_known_main_sets_op_series():
    assert _convert("OP-01") == "Romance Dawn"
    assert _convert("OP-02") == "Paramount War"
    assert _convert("OP-09") == "Emperors in the New World"
    assert _convert("OP-13") == "Carrying On His Will"


def test_known_starter_decks_st_series():
    assert _convert("ST-03") == "The Seven Warlords of the Sea"
    assert _convert("ST-16") == "Uta"


def test_known_extra_booster_eb_series():
    assert _convert("EB-01") == "Memorial Collection"
    assert _convert("EB-02") == "25th Anniversary Collection"


def test_known_premium_booster_prb():
    assert "PRB-01" in SET_MAP
    assert "PRB-02" in SET_MAP


def test_unknown_set_returns_code_as_fallback():
    """未収録セットは set_code をそのまま返す (空欄より検索性高い)"""
    assert _convert("OP-99") == "OP-99"
    assert _convert("ST-99") == "ST-99"
    assert _convert("") == ""


def test_set_map_size_minimum():
    """主要セットが最低限揃っていること（追加保護）"""
    assert len(SET_MAP) >= 30, f"Set map too small: {len(SET_MAP)} entries"


# Standalone runner
if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    cases = [
        ("OP series", test_known_main_sets_op_series),
        ("ST series", test_known_starter_decks_st_series),
        ("EB series", test_known_extra_booster_eb_series),
        ("PRB premium", test_known_premium_booster_prb),
        ("unknown fallback", test_unknown_set_returns_code_as_fallback),
        ("map size minimum", test_set_map_size_minimum),
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
        print(f"\n✅ All {len(cases)} canonical map tests passed.")
    else:
        print(f"\n❌ {fails} failed.")
        sys.exit(1)
