# -*- coding: utf-8 -*-
"""Stage2: スプシ集約 共有ヘルパ sheet_io の定数・シグネチャ。"""
import importlib.util
import os

_SI = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "tools", "sheet_io.py"))


def _load():
    spec = importlib.util.spec_from_file_location("sheet_io_t", _SI)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_maint_constants():
    si = _load()
    assert si.MAINT_SHEET_ID == "1UAVBdosIqqOI8qx-P-4k_ftTGuGWGzfIOU7vk7S2dz4"
    assert si.MAINT_URL.startswith("https://docs.google.com/spreadsheets/d/")
    assert si.MAINT_SHEET_ID in si.MAINT_URL
    assert callable(si.write_rows_to_tab)
