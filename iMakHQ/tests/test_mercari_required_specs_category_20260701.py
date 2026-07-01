#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Mercari check_csv の REQUIRED_SPECIFICS category-aware 回帰テスト (2026-07-01)。

事故: バッグ(57988/52357)に apparel spec の C:Type/C:Size を必須扱いしていたため
Porter が毎回「必須 C:Type 空」で誤検出→監査くん再発の主因(9件)。
→ required_specifics_for(category) で category-aware 化。その回帰固定。

不変条件:
  - バッグ category は C:Type / C:Size を必須にしない (Porter 誤検出の根を断つ)。
  - apparel(Clothing 11450 / T-shirts 15687) は C:Type/C:Size 必須のまま維持。
"""
import importlib.util
import os

_MERCARI = os.path.join(os.path.dirname(__file__), "..", "..", "iMakMercari", "check_csv.py")


def _load():
    spec = importlib.util.spec_from_file_location("mercari_check_csv", _MERCARI)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_bag_category_not_require_ctype_csize():
    mod = _load()
    for cat in ("57988", "52357"):
        req = mod.required_specifics_for(cat)
        assert "C:Type" not in req, f"bag {cat} should not require C:Type"
        assert "C:Size" not in req, f"bag {cat} should not require C:Size"
        # バッグでも Brand/Color/Department/Style は必須
        assert set(req) >= {"C:Brand", "C:Color", "C:Department", "C:Style"}


def test_apparel_category_keeps_ctype():
    mod = _load()
    for cat in ("11450", "15687"):
        req = mod.required_specifics_for(cat)
        assert "C:Type" in req, f"apparel {cat} must keep C:Type"
        assert "C:Size" in req


def test_unknown_category_defaults_apparel():
    mod = _load()
    # 未知/空は apparel 既定(安全側=必須多め)
    assert mod.required_specifics_for("") == mod._REQUIRED_APPAREL
    assert mod.required_specifics_for("99999") == mod._REQUIRED_APPAREL


def test_backcompat_default_symbol():
    mod = _load()
    # 既存 import 用の REQUIRED_SPECIFICS は apparel 既定のまま
    assert mod.REQUIRED_SPECIFICS == mod._REQUIRED_APPAREL
