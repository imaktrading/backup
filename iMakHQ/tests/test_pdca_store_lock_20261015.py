# -*- coding: utf-8 -*-
"""2026-10-15 監査記録 DB (pdca.db) を同時に開くと 5秒で database is locked になり、PDCA の積み上げが抜けていた。"""
import os
import sqlite3
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))


def test_connect_waits_for_a_short_lock(tmp_path):
    import pdca_store as P
    db = str(tmp_path / "pdca.db")
    P.connect(db).close()
    holder = sqlite3.connect(db, check_same_thread=False)
    holder.execute("BEGIN EXCLUSIVE")

    def release():
        time.sleep(6)                     # 既定の5秒より長く握る
        holder.rollback()
        holder.close()
    threading.Thread(target=release).start()
    con = P.connect(db)                   # 以前はここで database is locked
    assert con.execute("PRAGMA busy_timeout").fetchone()[0] == 60000
    con.close()


def test_consolidated_request_rings_bravo_bell():
    """2026-10-15 残務 №547: まとめ依頼を書いたらブラボーの呼び鈴を鳴らす"""
    import inspect
    import pdca_store as P
    src = inspect.getsource(P.emit_consolidated_request)
    assert "notify_bg(" in src and src.index("write_text") < src.index("notify_bg(")
