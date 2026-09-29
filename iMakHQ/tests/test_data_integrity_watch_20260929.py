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


def test_direction_repaired_value_is_not_reported():
    """2026-09-30: 「前」が化けていて「今」が直った値だった10欄に「前に戻せ」と出した。前のどれかに今の値があれば外す。"""
    cols = ["category", "product_id", "language"]
    older = {1: (b"p", b"A", b"ja")}                                  # 化ける前
    old = {1: (b"p", b"A", b"na")}                                    # 化けたまま2日残った
    new = {1: (b"p", b"A", b"ja")}                                    # 直った
    fl = W.bitflips(old, new, cols)
    assert len(fl) == 1
    assert W.classify(fl, old, new, [old, older], cols) == []


def test_direction_new_flip_and_unknown():
    cols = ["category", "product_id", "language"]
    old = {1: (b"p", b"A", b"ja"), 2: (b"p", b"B", b"ja")}
    new = {1: (b"p", b"A", b"na"), 2: (b"p", b"B", b"na")}
    ref = {1: (b"p", b"A", b"ja")}                                    # 2 は2つ前に無い
    got = W.classify(W.bitflips(old, new, cols), old, new, [ref], cols)
    assert {f["rowid"]: f["broken"] for f in got} == {1: "now", 2: "unknown"}
