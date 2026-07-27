# -*- coding: utf-8 -*-
"""★PSA10 以外を出品しない (2026-07-27 実事故の再発防止)。

## 事故
cert152687772 Dragon Ball E-60 Energy Marker は **実物 PSA 9**(ラベル "MINT 9") なのに、
CSV は `PSA 10 Dragon Ball Manga Booster 01 #E-60 Energy Marker 2025` / CustomLabel
`PSA10-152687772` / `C:Grade=10` で生成され、**$494.98 で入稿寸前**だった。

## 真因: パイプライン全体が PSA10 限定運用の前提
- `build_title()` は `prefix = "PSA 10"` 固定
- `build_row` は `C:Grade = "10"` 固定
- 新コア override が その C:Grade を読んでタイトルを `PSA 10 ...` に再生成
  → **Claude が画像から正しく出していた `PSA 9 ...` が上書きされた**
- 市場ゲートも "PSA 10 ..." で検索 → PSA10 相場(中央値$8,450)を引き **GO(利益71%)** と誤判定

## この gate の方針
現物ラベル由来のタイトルで **PSA10 以外と判った時だけ止める**。読めない時は従来どおり続行
(ここで全部止めると出品がゼロになる)。= 判っている誤りだけを確実に潰す fail-closed。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from psa_to_csv import detected_grade_from_title, is_psa10_or_unknown  # noqa: E402


def test_detect_grade():
    assert detected_grade_from_title("PSA 9 Dragon Ball SCG Manga Booster 01 #E-60 Energy Marker Card") == "9"
    assert detected_grade_from_title("PSA 10 Pokemon Japanese Crimson Haze #083/066 Greninja ex") == "10"
    assert detected_grade_from_title("psa 8 something") == "8"
    assert detected_grade_from_title("Pokemon Card without grade") is None
    assert detected_grade_from_title("") is None
    assert detected_grade_from_title(None) is None


def test_psa9_is_blocked():
    """★本命: PSA9 は出品させない。"""
    assert is_psa10_or_unknown("PSA 9 Dragon Ball SCG Manga Booster 01 #E-60 Energy Marker Card") is False


def test_psa10_passes():
    assert is_psa10_or_unknown("PSA 10 One Piece Two Legends #OP08-058 Charlotte Pudding Alt Art") is True


def test_unknown_grade_passes():
    """読めない時は止めない(出品ゼロにしない)。従来挙動を維持する。"""
    assert is_psa10_or_unknown("One Piece #OP08-058 Charlotte Pudding") is True
    assert is_psa10_or_unknown(None) is True


def test_other_low_grades_blocked():
    for t in ("PSA 8 x", "PSA 7 y", "PSA 1 z"):
        assert is_psa10_or_unknown(t) is False, t
