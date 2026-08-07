#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gshock_parity_check 純関数の回帰テスト (2026-06-14)。

固定する不変条件:
  - model 抽出: *Title 'CASIO G-Shock <MODEL> ...' から型番を取り出す。
  - 分類: CSV値 vs catalog期待値 を OK/GAP_FILLABLE/CATALOG_GAP/DRIFT に正しく振る。
    特に「両方値ありで不一致 = DRIFT(誤値検出)」を崩さない (MTG-B3000D Band Black≠Silver 型)。
"""
import importlib.util
import os

_TOOL = os.path.join(os.path.dirname(__file__), "..", "tools", "gshock_parity_check.py")


def _load():
    spec = importlib.util.spec_from_file_location("gshock_parity_check", _TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_extract_model():
    m = _load()
    assert m.extract_model("CASIO G-Shock GST-W310-1A Mens Watch Black Sport") == "GST-W310-1A"
    assert m.extract_model("CASIO G-Shock GMW-B5000D-2 Metal Covered Mens Digital") == "GMW-B5000D-2"
    assert m.extract_model("no model token here") == ""


def test_classify_ok():
    m = _load()
    assert m.classify("C:Dial Color", "Black", "Black")[0] == "ok"
    assert m.classify("C:Movement", "Quartz", "quartz")[0] == "ok"  # 正規化で一致


def test_classify_gap_fillable():
    m = _load()
    # CSV 空 / catalog 値あり = 充填可
    assert m.classify("C:Movement", "", "Quartz")[0] == "gap_fillable"
    assert m.classify("C:Features", "", "Bluetooth")[0] == "gap_fillable"


def test_classify_catalog_gap():
    m = _load()
    # CSV 値あり / catalog 空 = catalog 拡充候補
    assert m.classify("C:Case Size", "44 mm", "")[0] == "catalog_gap"


def test_classify_drift_is_real_mismatch():
    m = _load()
    # 両方値ありで不一致 = DRIFT (誤値出品の検出。MTG-B3000D Band Black≠Silver 型)
    assert m.classify("C:Band Color", "Black", "Silver")[0] == "drift"
    assert m.classify("C:Movement", "Quartz", "Solar Quartz")[0] == "drift"


def test_classify_title():
    m = _load()
    assert m.classify("*Title", "old title", "new title")[0] == "drift"
    assert m.classify("*Title", "", "gen title")[0] == "gap_fillable"
