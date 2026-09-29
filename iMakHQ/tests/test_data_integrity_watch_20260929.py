# -*- coding: utf-8 -*-
"""毎朝のデータの見張り: 1ビット化けだけを拾い、普通の書き換えは拾わない (2026-09-29)。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import data_integrity_watch as W  # noqa: E402

COLS = ["category", "product_id", "images"]


def test_single_bit_flip_is_found():
    old = {1: (b"pokemon", b"MC-409", b"large/MC/049125_P")}
    new = {1: (b"pokemon", b"MC-409", b"large/MC/849125_P")}       # '0'(0x30) → '8'(0x38) = 1ビット
    got = W.bitflips(old, new, COLS)
    assert len(got) == 1 and got[0]["column"] == "images" and got[0]["bits"] == ["0x8"]


def test_normal_edits_are_not_flips():
    old = {1: (b"a", b"X", b"Pokemon"), 2: (b"a", b"Y", b"abc")}
    new = {1: (b"a", b"X", b"pokemon"),                               # 大文字小文字 (0x20) = 人の直し
           2: (b"a", b"Y", b"abcdef"),                                # 長さが違う = 普通の書き換え
           3: (b"a", b"Z", b"new")}                                   # 新しい行
    assert W.bitflips(old, new, COLS) == []


def test_backup_calls_the_watch():
    src = open(os.path.join(os.path.dirname(W.__file__), "data_backup.py"), encoding="utf-8").read()
    assert "data_integrity_watch.run()" in src
