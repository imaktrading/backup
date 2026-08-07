#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""psa_to_csv: 番号なし DON!! カードを out-of-scope skip (2026-07-02)。

PSA データで card番号欠落(#None)の DON!! カードは変種特定不能 → catalog key 付与も出品も
できない(fail-closed)。Catalog 収録却下・Gemini 諮問「入力データ構造的に特定不能=握りつぶし
でなく処理境界の定義。即時skip妥当」。番号有り DON は listable なので skip しないことを固定。
"""
import importlib.util
import os
import sys

_TCG_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "iMakTCG"))
_PSA = os.path.join(_TCG_DIR, "psa_to_csv.py")


def _load():
    if _TCG_DIR not in sys.path:
        sys.path.insert(0, _TCG_DIR)
    spec = importlib.util.spec_from_file_location("psa_to_csv_mod", _PSA)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_don_without_number_skipped():
    m = _load()
    assert m.is_unidentifiable_don_card("DON!! CARD", "")
    assert m.is_unidentifiable_don_card("DON!! CARD", None)


def test_don_with_number_not_skipped():
    m = _load()
    # 番号有り DON は listable → skip しない(recall損防止)
    assert not m.is_unidentifiable_don_card("DON!! CARD", "DON-PRB01-027")


def test_non_don_not_skipped():
    m = _load()
    assert not m.is_unidentifiable_don_card("MONKEY D. LUFFY", "")
    assert not m.is_unidentifiable_don_card("TASHIGI OFFICIAL EVENT PRIZE", "031")
    assert not m.is_unidentifiable_don_card("", "")
