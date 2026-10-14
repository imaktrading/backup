"""数え直しで注文の取り込みを一番先に回す (時間切れでも仕入れ待ちが新しくなる・2026-10-14)。"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))


def test_order_sync_runs_first():
    src = open(os.path.join(HERE, "..", "console", "counts.py"), encoding="utf-8").read()
    i = src.index("fns = {")
    body = src[i:i + 1200]
    assert body.index('"order": order_sync') < body.index('"hoju":')
    assert src.count('"order": order_sync') == 1
