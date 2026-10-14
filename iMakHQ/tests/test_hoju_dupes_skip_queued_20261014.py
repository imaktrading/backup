# -*- coding: utf-8 -*-
"""2枚目→補URL の自動追記: 既に目視待ちに居る (行, URL) は在庫を確かめない (2026-10-14)。

確かめても積まれないのに毎回 約350本を API で確かめ、5分の上限で時間切れになっていた
(10/2〜10/14 の22回。実測 353本中 342本が既に目視待ち)。PSA の 🤖自動 の後処理が5分短くなる。
"""
import os

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools", "hoju_url_from_dupes.py")


def test_queued_pairs_are_dropped_before_verify():
    s = open(SRC, encoding="utf-8").read()
    m = s[s.index("def main("):]
    assert m.index("queued_pairs()") < m.index("verify_alive(_keep)")
    assert "既に目視待ちに居るので確かめない" in m
