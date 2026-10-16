# -*- coding: utf-8 -*-
"""2026-10-16 B-20261016-006: _pdca_prune_resolved が記録 DB を開いたまま放さず、後ろの積み上げが locked で抜けていた。"""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))


def test_prune_releases_lock_so_next_writer_can_write(tmp_path, monkeypatch):
    import csv_auditor as A
    import pdca_store as P
    db = str(tmp_path / "pdca.db")
    monkeypatch.setattr(P, "DB_PATH", db)
    monkeypatch.setattr(P, "prune_resolved_gaps", lambda con, res, ts="": (con.execute(
        "CREATE TABLE IF NOT EXISTS t(x)"), con.execute("INSERT INTO t VALUES (1)"), {"pruned": 1, "pruned_item_ids": []})[2])
    monkeypatch.setattr(P, "make_catalog_resolver", lambda db: None)
    monkeypatch.setattr(P, "sync_processed", lambda con, d, ts="": 0)
    monkeypatch.setattr(A, "_move_resolved_missing_models", lambda ids: 0)
    assert A._pdca_prune_resolved(False) == 1
    other = sqlite3.connect(db, timeout=1)          # 鍵を握ったままなら 1秒で locked になる
    other.execute("INSERT INTO t VALUES (2)")
    other.commit()
    assert other.execute("SELECT count(*) FROM t").fetchone()[0] == 2   # 先の書込みも commit されている
