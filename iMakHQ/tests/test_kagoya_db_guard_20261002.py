"""壊れたカタログ DB を KAGOYA に送らない (2026-10-02: 08:20 に壊れた DB を送っていた)。"""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
import kagoya_offload as K  # noqa: E402


def test_healthy_db_passes(tmp_path):
    p = str(tmp_path / "a.sqlite")
    c = sqlite3.connect(p)
    c.execute("create table t(x)")
    c.commit()
    c.close()
    assert K.db_is_healthy(p)


def test_broken_or_missing_db_is_not_sent(tmp_path):
    p = tmp_path / "b.sqlite"
    p.write_bytes(b"SQLite format 3\x00" + b"\xff" * 4000)
    assert not K.db_is_healthy(str(p))
    assert not K.db_is_healthy(str(tmp_path / "none.sqlite"))
