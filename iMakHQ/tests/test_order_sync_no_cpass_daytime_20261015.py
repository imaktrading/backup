# -*- coding: utf-8 -*-
"""昼の自動の数え直しでは CPaSS を開かない。送料は夜の予約と「📦 注文の取り込み」を押した時だけ
(2026-10-15 ユーザー「作業中に突然出るからさ」→「夜」)。"""
import os

T = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


def test_counts_turns_off_cpass_and_sync_respects_it():
    counts = open(os.path.join(T, "console", "counts.py"), encoding="utf-8").read()
    sync = open(os.path.join(T, "tools", "order_purchase_sync.py"), encoding="utf-8").read()
    assert 'ORDER_SYNC_NO_CPASS="1"' in counts
    a = sync.index('os.environ.get("ORDER_SYNC_NO_CPASS") == "1"')
    assert a < sync.index("fees = CF.fetch()")
