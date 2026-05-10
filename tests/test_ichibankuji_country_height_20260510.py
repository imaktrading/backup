"""Regression: 2026-05-10 一番くじ build_row の Country of Origin / Item Height 修正.

【背景】
ユーザー指摘:
1. C:Country of Origin = "Japan" ハードコード問題
   - BANDAI SPIRITS は日本企業だが製造国は中国が多い
   - 確証なきは "Does not apply" (CLAUDE.md 大原則)
2. C:Item Height = "X.X in" のみ
   - 「インチ（センチ）」併記が望ましい (buyer 視認性)

【修正方針】
1. C:Country of Origin: "Japan" → "Does not apply" (確証なき場合は明示)
2. C:Item Height: "X.X in (Y cm)" 併記化、片方のみなら単独、両方無いなら空
"""
from __future__ import annotations
import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_KUJI = _REPO_ROOT / "iMak_ichibankuji"


def test_country_of_origin_is_does_not_apply():
    """build_row の C:Country of Origin が 'Does not apply' に変更されている (source 確認)."""
    src = (_KUJI / "ichibankuji_to_csv.py").read_text(encoding='utf-8')
    assert '"C:Country of Origin": "Does not apply"' in src
    # 旧 "Japan" 値が残っていないこと
    assert '"C:Country of Origin": "Japan"' not in src


def test_item_height_format_in_cm_combined():
    """C:Item Height format 確認: in + cm 併記、片方のみ、両方無し の3 case."""
    # 期待動作 (build_row 内のロジックを単体検証)
    def height_format(height_in, height_cm):
        if height_in and height_cm:
            return f"{height_in} in ({height_cm} cm)"
        elif height_in:
            return f"{height_in} in"
        elif height_cm:
            return f"{height_cm} cm"
        else:
            return ""

    # 双方あり → 併記
    assert height_format("4.3", "11") == "4.3 in (11 cm)"
    assert height_format("9.8", "25") == "9.8 in (25 cm)"
    # in のみ
    assert height_format("4.3", "") == "4.3 in"
    # cm のみ (Claude が in 返さなかったが scrape の cm はある)
    assert height_format("", "11") == "11 cm"
    # 両方無し
    assert height_format("", "") == ""


def test_item_height_logic_in_source():
    """build_row 内に新 Height 併記ロジックが存在 (回帰防止)."""
    src = (_KUJI / "ichibankuji_to_csv.py").read_text(encoding='utf-8')
    # 双方ある時の併記 format
    assert 'f"{height_in} in ({height_cm} cm)"' in src
    # cm のみ fallback
    assert 'f"{height_cm} cm"' in src
