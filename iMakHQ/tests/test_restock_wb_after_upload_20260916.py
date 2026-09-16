# -*- coding: utf-8 -*-
"""②で作って上げた行が ③(確認) の対象から消えていた件 (2026-09-16 ユーザー指摘)。

②は「作れない行」と「今日もう作った行」を同じ袋 (blocked_iids) で返しており、
③はその袋を「押しても無駄」として引いていた。結果、**CSV を上げた直後の行こそ
③で確かめたいのに、③の件数が必ず 0 になり「今日やること」に出なかった**。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
sys.path.insert(0, os.path.normpath(os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "iMakeBayAPI")))

import psa_restock_build as B          # noqa: E402
import psa_restock_writeback as W      # noqa: E402

IID, CERT = "358411384330", "153671408"
ROWS = [["itemID", "最安¥", "仕入URL", "RESTOCK状態", "確認済仕入URL"],
        [IID, "38000", "https://jp.mercari.com/item/m1", "", "https://jp.mercari.com/item/m1"]]


def _built_today(monkeypatch, ids):
    monkeypatch.setattr(B, "built_today", lambda *a, **k: set(ids))
    monkeypatch.setattr(B, "undeliverable", lambda *a, **k: {})


def test_built_today_is_not_reported_as_unbuildable(monkeypatch):
    """今日作った行は「作れない行」に混ぜない (袋を分ける)。"""
    _built_today(monkeypatch, [IID])
    r = B.count_workload(ROWS, itemid_to_cert={IID: CERT})
    assert r["actionable"] == 0                    # ②はもう押さなくていい
    assert r["built_today_iids"] == [IID]
    assert IID not in r["blocked_iids"]


def test_writeback_counts_the_row_we_just_uploaded(monkeypatch):
    """CSV を上げた直後の行は ③(確認) の対象 = 今日やることに出る。"""
    _built_today(monkeypatch, [IID])
    r = W.count_workload(ROWS, itemid_to_cert={IID: CERT})
    assert r["actionable"] == 1


def test_writeback_still_skips_rows_that_cannot_be_built(monkeypatch):
    """cert が引けない行は ③でも押して進まないので、これまで通り数えない。"""
    _built_today(monkeypatch, [])
    r = W.count_workload(ROWS, itemid_to_cert={})  # cert 未解決
    assert r["actionable"] == 0
