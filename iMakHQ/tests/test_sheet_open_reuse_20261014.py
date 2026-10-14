# -*- coding: utf-8 -*-
"""スプシは1つのプロセスの中で開き直さない (10分まで使い回す) / ③ の在庫確認は同時に聞く (2026-10-14)。

ユーザー「目視して在庫を戻す、20分やで」。① はタブを読むたびにスプシを開き直して約30秒、
③ は164件の在庫数を1件ずつ聞いて約8分かかっていた。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))

import sheet_io as S  # noqa: E402


def test_open_reuses_within_ttl(monkeypatch):
    import gspread
    from google.oauth2 import service_account
    n = {"open": 0}

    class _GC:
        def open_by_key(self, k):
            n["open"] += 1
            return ("sheet", k, n["open"])

    monkeypatch.setattr(service_account.Credentials, "from_service_account_file", lambda *a, **k: None)
    monkeypatch.setattr(gspread, "authorize", lambda c: _GC())
    monkeypatch.setattr(S, "_OPENED", {})
    a = S._open("X")
    assert S._open("X") is a and n["open"] == 1
    monkeypatch.setattr(S, "_OPEN_TTL_SEC", -1)            # 期限切れ → 開き直す
    assert S._open("X") is not a and n["open"] == 2


def test_writeback_asks_ebay_in_parallel():
    import psa_restock_writeback as W
    assert W.GETITEM_WORKERS > 1
    src = open(W.__file__, encoding="utf-8").read()
    assert "ThreadPoolExecutor" in src and "⏱ eBay の在庫数を確かめた" in src
