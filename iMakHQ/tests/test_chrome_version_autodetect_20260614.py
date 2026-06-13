#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""uc version_main 自動検出化の回帰テスト (master, 2026-06-14)。

横断ルール (global CLAUDE.md 2026-06-13): undetected_chromedriver の version_main に
major version を数値ハードコードしない。実 Chrome を検出して渡す / 失敗時 None。

不変条件:
  - detect_chrome_major() は int(>0) か None を返す (例外を投げない)。
  - master の listing/viewer スクリプトに `version_main=<数値>` が再混入しない
    (= driver 起動不能事故 2026-06-13 の回帰防止)。
"""
import importlib.util
import os
import re

_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
_UTIL = os.path.join(_ROOT, "iMakeBayAPI", "chrome_util.py")

# numeric pin を持っていてはいけない master 上のファイル (相対パス)
_GUARDED = [
    os.path.join("iMakTCG", "psa_to_csv.py"),
    os.path.join("iMakeBayAPI", "seller_hub_view.py"),
    os.path.join("iMakeBayAPI", "chrome_util.py"),
]
_NUMERIC_PIN = re.compile(r"version_main\s*=\s*\d+")


def _load_util():
    spec = importlib.util.spec_from_file_location("imakebay_chrome_util", _UTIL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_detect_returns_int_or_none():
    mod = _load_util()
    v = mod.detect_chrome_major()
    assert v is None or (isinstance(v, int) and v > 0)


def test_no_numeric_version_main_pin_on_master():
    offenders = []
    for rel in _GUARDED:
        path = os.path.join(_ROOT, rel)
        with open(path, encoding="utf-8") as f:
            src = f.read()
        for m in _NUMERIC_PIN.finditer(src):
            offenders.append(f"{rel}: {m.group(0)}")
    assert not offenders, "numeric version_main pin 残存: " + "; ".join(offenders)
