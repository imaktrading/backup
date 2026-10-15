# -*- coding: utf-8 -*-
"""2026-10-15 残務 №495: PSA にページが無い cert は枠を選ぶ前に外す (判定は psa_cache_warm を使い回す)。"""
import inspect
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_uses_psa_cache_warm_ledger_before_slot_selection():
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "psa_to_csv.py"),
               encoding="utf-8").read()
    i = src.index("PSA にページが無い cert (30日以内に記録) を枠の前に外した")
    j = src.index("★2026-08-11: **枠を選ぶ前に** catalog で解決できない cert を落とす")
    assert i < j                                   # 枠を選ぶ前の preflight より前
    block = src[src.rfind("try:", 0, i):i]
    assert "_pcw.recently_not_found" in block and "_pcw._load_not_found" in block   # 同じ判定を2つ書かない


def test_recently_not_found_window():
    from datetime import datetime
    import psa_cache_warm as P
    led = {"1": "2026-10-10T00:00:00", "2": "2026-08-01T00:00:00"}
    now = datetime(2026, 10, 15)
    assert P.recently_not_found("1", led, now) and not P.recently_not_found("2", led, now)
    assert not P.recently_not_found("3", led, now)
