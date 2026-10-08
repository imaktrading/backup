# -*- coding: utf-8 -*-
"""digest の前の片付けで、カタログが処理済にした依頼も閉じる (2026-10-09・Act 提案 2026-10-06 提案1)。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
import csv_auditor as A
import pdca_store as P


def test_prune_resolved_also_syncs_processed(monkeypatch):
    called = []
    monkeypatch.setattr(P, "connect", lambda *a, **k: "con")
    monkeypatch.setattr(P, "make_catalog_resolver", lambda *a, **k: None)
    monkeypatch.setattr(P, "prune_resolved_gaps", lambda *a, **k: {"pruned": 0, "pruned_item_ids": []})
    monkeypatch.setattr(P, "sync_processed", lambda con, d, ts="": called.append((con, d)) or 4)
    monkeypatch.setattr(A, "_move_resolved_missing_models", lambda *a, **k: 0)
    A._pdca_prune_resolved(dry_run=False)
    assert called == [("con", A.CATALOG_REQ_DIR)]


def test_dry_run_writes_nothing(monkeypatch):
    monkeypatch.setattr(P, "sync_processed", lambda *a, **k: (_ for _ in ()).throw(AssertionError("呼ばない")))
    assert A._pdca_prune_resolved(dry_run=True) == 0
