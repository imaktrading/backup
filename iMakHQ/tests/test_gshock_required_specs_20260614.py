#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""G-shock check_csv の REQUIRED_SPECIFICS 回帰テスト (2026-06-14)。

不変条件 (出品の正確性 / 誤除外防止):
  - C:Color は eBay cat 31387 に "Color" aspect が存在しない (Dial/Band/Bezel/Case Color
    のみ) ため、phantom 必須として REQUIRED_SPECIFICS から外れていること。
    = 「必須 'C:Color' が空」WARN を二度と出さない (csv_auditor の誤除外回帰の根。
       2026-06-13 に spec_empty_excludes:False で除外は停止済、本テストは phantom 必須
       そのものの再混入を防ぐ)。
  - eBay aspect_required=True の Brand / Type は必須のまま維持。
"""
import importlib.util
import os

_GSHOCK = os.path.join(os.path.dirname(__file__), "..", "..", "iMakG-shock", "check_csv.py")


def _load():
    spec = importlib.util.spec_from_file_location("gshock_check_csv", _GSHOCK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_color_not_required_phantom():
    mod = _load()
    assert "C:Color" not in mod.REQUIRED_SPECIFICS


def test_ebay_required_aspects_kept():
    mod = _load()
    # cat 31387 で aspect_required=True
    assert "C:Brand" in mod.REQUIRED_SPECIFICS
    assert "C:Type" in mod.REQUIRED_SPECIFICS
