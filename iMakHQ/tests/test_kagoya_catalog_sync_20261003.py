"""カタログ DB の正本を KAGOYA に置いた後の、家との行き来 (2026-10-03 段階C)。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
import kagoya_catalog_sync as S  # noqa: E402

A = [100.0, 10]
B = [200.0, 11]
C = [300.0, 12]


def test_new_on_one_side_is_copied():
    p = S.plan_twoway({"a.md": A}, {"b.md": B}, {})
    assert p["push"] == ["a.md"] and p["pull"] == ["b.md"]


def test_changed_on_one_side_wins():
    p = S.plan_twoway({"a.md": B}, {"a.md": A}, {"a.md": A})
    assert p["push"] == ["a.md"] and not p["conflicts"]
    p = S.plan_twoway({"a.md": A}, {"a.md": B}, {"a.md": A})
    assert p["pull"] == ["a.md"]


def test_rename_to_processed_does_not_come_back():
    """KAGOYA で _processed に改名 → 家の古い名前は消える (戻ってこない)。"""
    p = S.plan_twoway({"x.md": A}, {"x_processed.md": A}, {"x.md": A})
    assert p["del_local"] == ["x.md"] and p["pull"] == ["x_processed.md"]


def test_both_changed_newer_wins_and_is_reported():
    p = S.plan_twoway({"a.md": C}, {"a.md": B}, {"a.md": A})
    assert p["push"] == ["a.md"] and p["conflicts"] == ["a.md"]


def test_db_marker_and_pending_are_never_synced():
    """DB 本体・家だけの印・控えは両方向の写しに入れない (印を KAGOYA に写すと正本が読むだけになる)。"""
    for n in ("products.sqlite", "products.sqlite-wal", "products.sqlite.bak_20261003",
              "_REPLICA_READ_ONLY", "_replica_pending_writes.jsonl"):
        assert S.skip_name(n)
    p = S.plan_twoway({"_REPLICA_READ_ONLY": A, "products.sqlite": A}, {}, {})
    assert not p["push"]


def test_copy_time_rounding_counts_as_same():
    p = S.plan_twoway({"a.md": [100.0, 10]}, {"a.md": [101.5, 10]}, {})
    assert not any(p.values())


def test_sync_only_when_db_master_is_kagoya():
    assert S.db_master_is_kagoya({"db_master": "kagoya"})
    assert not S.db_master_is_kagoya({})
