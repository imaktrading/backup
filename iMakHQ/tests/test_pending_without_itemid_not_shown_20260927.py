"""補URL③: itemID の無い目視待ちを、今の行番号から別の出品に付けない (2026-09-27)。

ダークライGX (358874018883, 行1320) にカビゴンの候補が並んだ。9/10 に行1320 だった別の出品の分を、
今の行1320 の出品に付けていた (行は日々ずれる)。
"""
import os

SRC = open(os.path.join(os.path.dirname(__file__), "..", "tools", "psa_hoju_fill.py"),
           encoding="utf-8").read()


def test_pending_without_itemid_is_skipped():
    i = SRC.index("for _r in aux_pending.load():")
    body = SRC[i:i + 900]
    assert '_iid = (_r.get("itemID") or "").strip()' in body
    assert "_cell(vals[_row - 1], B)" not in body
