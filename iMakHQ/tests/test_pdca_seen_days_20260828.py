# -*- coding: utf-8 -*-
"""同じCSVを その日のうちに2回 監査しただけで「再発」にしない (2026-08-28)。

何が起きていたか: 8/28 の G-shock は 15:08 の upload と 15:10 の recheck で同じ1行を
2回 監査した。`upsert_improvement` は同 dkey を見つけると無条件に seen_count+1 するので、
1日で seen_count=2 に到達し、digest の「複数日 消えていない構造問題」に化けていた
(pdca.db queue_id 618/619 = created_ts も updated_ts も 2026-08-28)。

直し方: 観測回数 (seen_count) と 観測した日数 (seen_days) を分け、再発の判定は
seen_days>=2 で行う。出典: hq/requests/2026-08-28_act_code_proposals_gshock_response.md 提案3
"""
import os
import sqlite3
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(_HERE, "..", "tools")))

import csv_auditor as ca      # noqa: E402
import pdca_store as ps       # noqa: E402


def _up(con, ts, **kw):
    return ps.upsert_improvement(con, "gshock", "GA-010GGB-1A9", "catalog_add",
                                 finding_type="catalog_gap", ts=ts, **kw)


# ---------------------------------------------------------------- store 側

def test_same_day_reaudit_does_not_bump_seen_days():
    con = ps.connect(":memory:")
    qid = _up(con, "2026-08-28")                 # upload 15:08
    assert _up(con, "2026-08-28") == qid         # recheck 15:10 = 同じ行
    r = con.execute("SELECT seen_count, seen_days FROM improvement_queue").fetchone()
    assert r["seen_count"] == 2, "観測回数は数える (優先度の材料)"
    assert r["seen_days"] == 1, "同日の再監査で「複数日」にしてはいけない"


def test_next_day_bumps_seen_days():
    con = ps.connect(":memory:")
    _up(con, "2026-08-28")
    _up(con, "2026-08-28")
    _up(con, "2026-08-29")
    r = con.execute("SELECT seen_count, seen_days FROM improvement_queue").fetchone()
    assert (r["seen_count"], r["seen_days"]) == (3, 2), "日をまたいだら 再発 1日分"


def test_missing_ts_does_not_inflate_seen_days():
    """日付が取れない時は増やさない (水増ししない側に倒す)。"""
    con = ps.connect(":memory:")
    _up(con, "2026-08-28")
    _up(con, "")
    r = con.execute("SELECT seen_days FROM improvement_queue").fetchone()
    assert r["seen_days"] == 1


def test_new_row_starts_at_one_day():
    con = ps.connect(":memory:")
    _up(con, "2026-08-28")
    r = con.execute("SELECT seen_count, seen_days FROM improvement_queue").fetchone()
    assert (r["seen_count"], r["seen_days"]) == (1, 1)


def test_migration_backfills_seen_days_from_created_vs_updated(tmp_path):
    """既存 pdca.db に列を足す時、実際に何日も消えていない行を 1 に潰さない。"""
    db = str(tmp_path / "old.db")
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE improvement_queue (queue_id INTEGER PRIMARY KEY AUTOINCREMENT,"
                " dkey TEXT UNIQUE, category TEXT, item_id TEXT, target_field TEXT,"
                " suggested_value TEXT, evidence TEXT, source TEXT, layer TEXT, confidence REAL,"
                " finding_type TEXT, seen_count INTEGER DEFAULT 1, priority REAL,"
                " status TEXT DEFAULT 'pending', created_ts TEXT, updated_ts TEXT, reviewed_ts TEXT)")
    con.execute("INSERT INTO improvement_queue (dkey, seen_count, created_ts, updated_ts)"
                " VALUES ('same-day', 2, '2026-08-28', '2026-08-28')")
    con.execute("INSERT INTO improvement_queue (dkey, seen_count, created_ts, updated_ts)"
                " VALUES ('multi-day', 2, '2026-08-27', '2026-08-28')")
    con.commit()
    con.close()

    con = ps.connect(db)                       # ← ここで _migrate が走る
    got = dict(con.execute("SELECT dkey, seen_days FROM improvement_queue").fetchall())
    assert got == {"same-day": 1, "multi-day": 2}
    con.close()
    ps.connect(db).close()                     # 冪等 (2回目で壊れない)
    con = ps.connect(db)
    assert dict(con.execute("SELECT dkey, seen_days FROM improvement_queue").fetchall()) == got


# ---------------------------------------------------------------- 監査くん側

def _f(item, days=None, count=1, status="pending"):
    r = {"category": "gshock", "item_id": item, "target_field": "catalog_add",
         "finding_type": "catalog_gap", "seen_count": count, "status": status}
    if days is not None:
        r["seen_days"] = days
    return r


def test_recurring_uses_seen_days_not_seen_count():
    rows = [
        _f("SAME-DAY-TWICE", days=1, count=2),   # 8/28 の 618/619 = 再発ではない
        _f("REALLY-STUCK", days=3, count=9),
    ]
    assert [r["item_id"] for r in ca.recurring_findings(rows)] == ["REALLY-STUCK"]


def test_recurring_falls_back_to_seen_count_for_old_rows():
    """seen_days を持たない古い行を欠測で取りこぼさない。"""
    rows = [_f("OLD", count=5), _f("OLD-ONESHOT", count=1)]
    assert [r["item_id"] for r in ca.recurring_findings(rows)] == ["OLD"]


def test_recurring_sorted_by_seen_days():
    rows = [_f("A", days=3), _f("B", days=10), _f("C", days=2)]
    assert [r["item_id"] for r in ca.recurring_findings(rows)] == ["B", "A", "C"]
