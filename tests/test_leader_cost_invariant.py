#!/usr/bin/env python3
"""Leader Cost 空欄維持 Invariant テスト (2026-04-28 Bug #2 修正).

eBay 出品仕様: One Piece TCG の Leader カードは C:Cost が空欄でなければならない.
DB の life_or_cost は Life 値 (Leader) と Cost 値 (Character/Event 等) の兼用カラムなので、
catalog_reference が無条件に life_or_cost を C:Cost に gap-fill すると Leader が壊れる.

修正案 C (A+B 二重防御):
  Fix A: catalog_reference.py — record.type_en=='Leader' なら cost gap-fill を skip
  Fix B: psa_to_csv.py — CSV 行 build 直前で defensive に Leader cost を再空欄化

このテストは Fix A の挙動を直接検証する (Fix B は build_row 全体を起動しないと再現しないため).
"""
from __future__ import annotations
import sys
from pathlib import Path

# iMakTCG のパスを通す (catalog_reference は iMakTCG/ にある)
_REPO_ROOT = Path(__file__).resolve().parent.parent
_TCG_ROOT = _REPO_ROOT / "iMakTCG"
if str(_TCG_ROOT) not in sys.path:
    sys.path.insert(0, str(_TCG_ROOT))

from catalog_reference import reference_catalog_for_specs  # noqa: E402


def test_catalog_reference_skips_cost_fill_for_leader():
    """Leader card (OP07-019 Bonney) は cost="" を渡されても catalog 側で再上書きされないこと."""
    out, _warnings = reference_catalog_for_specs(
        franchise="One Piece",
        card_number="OP07-019",
        current_specs={
            "cost": "",
            "power": "5000",
            "color": "Green",
            "card_type": "Leader",
        },
        psa_brand="ONE PIECE OP07",
        psa_subject="JEWELRY BONNEY",
    )
    # AUTO-FIX で空欄化された cost が catalog の life_or_cost='5' で再上書きされていないこと
    assert out["cost"] == "", (
        f"Leader cost が catalog_reference で再上書きされた: {out['cost']!r} "
        f"(expected: '')"
    )


def test_catalog_reference_still_fills_power_for_leader():
    """Leader card でも power 等の他フィールドの gap-fill 挙動は壊れていないこと."""
    out, _warnings = reference_catalog_for_specs(
        franchise="One Piece",
        card_number="OP07-019",
        current_specs={
            "cost": "",
            "power": "",  # 空欄
            "color": "Green",
            "card_type": "Leader",
        },
        psa_brand="ONE PIECE OP07",
        psa_subject="JEWELRY BONNEY",
    )
    # power は引き続き catalog 値で補完される (Leader 例外は cost のみ)
    assert out["power"] == "5000", (
        f"Leader power gap-fill が壊れた: {out['power']!r} (expected: '5000')"
    )


def test_catalog_reference_still_fills_cost_for_character():
    """Character card は cost gap-fill が引き続き動作すること (Fix A の regression check)."""
    # OP07-015 (Monkey.D.Dragon Character / Cost=8 / Power=9000)
    out, _warnings = reference_catalog_for_specs(
        franchise="One Piece",
        card_number="OP07-015",
        current_specs={
            "cost": "",  # 空欄
            "power": "9000",
            "color": "Green",
            "card_type": "Character",
        },
        psa_brand="ONE PIECE OP07",
        psa_subject="MONKEY D DRAGON",
    )
    # Character は従来通り catalog 値で補完される (Leader だけ skip)
    assert out["cost"] == "8", (
        f"Character cost gap-fill が壊れた: {out['cost']!r} (expected: '8')"
    )


# Standalone runner
if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    cases = [
        ("Leader cost stays empty", test_catalog_reference_skips_cost_fill_for_leader),
        ("Leader power still fills", test_catalog_reference_still_fills_power_for_leader),
        ("Character cost still fills", test_catalog_reference_still_fills_cost_for_character),
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
        print(f"\n✅ All {len(cases)} Leader Cost invariant tests passed.")
    else:
        print(f"\n❌ {fails} failed.")
        sys.exit(1)
