#!/usr/bin/env python3
"""ONE PIECE Canonical Map 正規化テスト.

旧 (~2026-04-25): psa_to_csv._ONEPIECE_SET_NAME_MAP の定数 dict を直接 exec
新 (2026-04-28以降): iMakCatalog/ebay_filter_map/one_piece.yaml + integrations/psa_to_csv.set_code_to_ebay_name()

iMakCatalog Phase 1 SSOT 移行で canonical map は iMakCatalog yaml に集約された。
このテストは iMakCatalog 経由で同じ assertion が通ることを確認し、
yaml 編集による意図しない値の喪失を golden test として検出する。
"""
from __future__ import annotations
import sys
from pathlib import Path

# iMakCatalog を sys.path に追加 (psa_to_csv.py と同じ流儀)
_REPO_ROOT = Path(__file__).resolve().parent.parent
_CATALOG_ROOT = _REPO_ROOT / "iMakCatalog"
if str(_CATALOG_ROOT) not in sys.path:
    sys.path.insert(0, str(_CATALOG_ROOT))

from integrations import psa_to_csv as catalog_psa  # noqa: E402


def _convert(set_code: str) -> str:
    return catalog_psa.set_code_to_ebay_name(set_code)


def test_known_main_sets_op_series():
    assert _convert("OP-01") == "Romance Dawn"
    assert _convert("OP-02") == "Paramount War"
    assert _convert("OP-09") == "Emperors in the New World"
    assert _convert("OP-13") == "Carrying On His Will"


def test_known_starter_decks_st_series():
    assert _convert("ST-03") == "The Seven Warlords of the Sea"
    # ★2026-08-02 更新: 旧 assertion は `ST-16 == "Uta"` だったが、これは **ST-11 (Uta) との
    #   silent collision** をそのまま golden として固定していた (= defect を正としていた)。
    #   公式を live 再取得したところ ST-11=`-Uta-` / ST-16=`-GREEN Uta-` で別セット。
    #   カタログが色 prefix を付けて解消したので、期待値も公式に合わせる。
    assert _convert("ST-16") == "GREEN Uta"


def test_same_character_starter_decks_do_not_collapse():
    """★同じキャラの別スターターが同じ値に潰れないこと (2026-08-02 追加).

    ST-18/26/31 が3セットとも `Monkey D Luffy` になっており、4/26 から 8/2 まで
    誰も気づかなかった。公式は色 (PURPLE / PURPLE/BLACK / RED) で区別している。
    ここを golden で固定して、集約に戻るのを防ぐ。
    """
    groups = [
        ["ST-08", "ST-18", "ST-26", "ST-31"],   # Monkey.D.Luffy 系
        ["ST-11", "ST-16"],                     # Uta 系
        ["ST-09", "ST-28"],                     # Yamato 系
        ["ST-20", "ST-34"],                     # Charlotte Katakuri 系
    ]
    for g in groups:
        vals = [_convert(c) for c in g]
        assert len(set(vals)) == len(vals), f"別セットが同じ値に潰れている: {dict(zip(g, vals))}"


def test_known_extra_booster_eb_series():
    assert _convert("EB-01") == "Memorial Collection"
    assert _convert("EB-02") == "25th Anniversary Collection"


def test_known_premium_booster_prb():
    """PRB-01 / PRB-02 が yaml に登録されており、未変換 fallback ではない eBay 値が返ること."""
    assert _convert("PRB-01") != "PRB-01"
    assert _convert("PRB-02") != "PRB-02"


def test_unknown_set_returns_code_as_fallback():
    """未収録セットは set_code をそのまま返す (空欄より検索性高い)."""
    assert _convert("OP-99") == "OP-99"
    assert _convert("ST-99") == "ST-99"
    assert _convert("") == ""


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
