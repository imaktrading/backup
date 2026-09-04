# -*- coding: utf-8 -*-
"""resolver_drop finding_type + reopen ガード + last_writer (2026-09-04)。

何が起きていたか: `_queue_resolver_drop` (resolver が「catalog に別idで在る」と判断して
依頼を出さず積む経路) が `finding_type="catalog_gap"` で積んでいたため、digest の再発判定
(`_load_pdca_recurring`) に永久に載り続けた (queue 610: cert155040105 が seen_count 723 まで
再トリアージされ続けた)。加えて `observed_ts`/`catalog_state` を渡していなかったため
`should_reopen` の2ガードが no-op になり、閉じた次の走行で必ず pending に戻っていた
(8/29・9/2 に実測)。queue が「誰の観測か」(last_writer) を持っていないため、この2つの
不具合の切り分けにも時間が掛かった。

出典: hq/requests/2026-09-02_act_code_proposals_tcg.md 提案1+2
      hq/requests/2026-09-03_act_code_proposals_tcg.md 提案4
      hq/requests/2026-09-02_act_code_proposals_tcg_response.md ([IMPLEMENT-GO])
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(_HERE, "..", "tools")))

import auto_catalog_add_request as acr        # noqa: E402
import csv_auditor as ca                      # noqa: E402
import pdca_store as ps                       # noqa: E402
import helper_last_writer_other_module_20260904 as other_mod  # noqa: E402


# ------------------------------------------------- 提案1: resolver_drop は再発扱いしない

def test_queue_resolver_drop_uses_resolver_drop_finding_type():
    con = ps.connect(":memory:")
    qid = acr._queue_resolver_drop(
        "one_piece_tcg", "155040105", "cert155040105 model text", "REVIEW", "ST17-004_p1",
        con=con)
    row = con.execute("SELECT finding_type,status FROM improvement_queue WHERE queue_id=?",
                      (qid,)).fetchone()
    assert row["finding_type"] == "resolver_drop"
    assert row["status"] == "pending"


def test_recurring_excludes_resolver_drop_but_keeps_catalog_gap():
    con = ps.connect(":memory:")
    # resolver_drop: 2日連続で観測 (seen_days=2) でも digest には出ない
    ps.upsert_improvement(con, "one_piece_tcg", "cert155040105", "catalog_add",
                          finding_type="resolver_drop", ts="2026-09-02")
    ps.upsert_improvement(con, "one_piece_tcg", "cert155040105", "catalog_add",
                          finding_type="resolver_drop", ts="2026-09-04")
    # catalog_gap: 同じ再発条件なら従来どおり digest に出る (回帰していないことの確認)
    ps.upsert_improvement(con, "one_piece_tcg", "cert999999", "catalog_add",
                          finding_type="catalog_gap", ts="2026-09-02")
    ps.upsert_improvement(con, "one_piece_tcg", "cert999999", "catalog_add",
                          finding_type="catalog_gap", ts="2026-09-04")

    rows = ca._load_pdca_recurring(_con=con)
    item_ids = [r["item_id"] for r in rows]
    assert "cert155040105" not in item_ids, "resolver_drop は再発 digest に載らない"
    assert "cert999999" in item_ids, "catalog_gap は従来どおり載る"


def test_resolver_drop_row_stays_in_queue_not_silently_dropped():
    """握り潰し禁止: digest から外れても queue の行自体は残る。"""
    con = ps.connect(":memory:")
    ps.upsert_improvement(con, "one_piece_tcg", "cert155040105", "catalog_add",
                          finding_type="resolver_drop", ts="2026-09-02")
    ps.upsert_improvement(con, "one_piece_tcg", "cert155040105", "catalog_add",
                          finding_type="resolver_drop", ts="2026-09-04")
    assert ca._load_pdca_recurring(_con=con) == []
    all_rows = con.execute("SELECT status, seen_days FROM improvement_queue").fetchall()
    assert len(all_rows) == 1
    assert all_rows[0]["status"] == "pending"
    assert all_rows[0]["seen_days"] == 2


# ------------------------------------------------- 提案2: 閉じた行が無条件で戻らない

def test_queue_resolver_drop_does_not_reopen_when_catalog_state_unchanged():
    con = ps.connect(":memory:")
    qid = acr._queue_resolver_drop(
        "one_piece_tcg", "155040105", "model text", "REVIEW", "ST17-004_p1", con=con)
    ps.set_status(con, qid, "done", ts="2026-01-01")   # 過去日に閉じたことにする

    acr._queue_resolver_drop(
        "one_piece_tcg", "155040105", "model text", "REVIEW", "ST17-004_p1", con=con)
    row = con.execute("SELECT status FROM improvement_queue WHERE queue_id=?", (qid,)).fetchone()
    assert row["status"] == "done", "catalog 側が変わっていない = 送り直しても答えは同じ"


def test_queue_resolver_drop_reopens_when_catalog_state_changed():
    con = ps.connect(":memory:")
    qid = acr._queue_resolver_drop(
        "one_piece_tcg", "155040105", "model text", "REVIEW", "ST17-004_p1", con=con)
    ps.set_status(con, qid, "done", ts="2026-01-01")

    acr._queue_resolver_drop(
        "one_piece_tcg", "155040105", "model text", "RESOLVED", "ST17-004_p2", con=con)
    row = con.execute("SELECT status FROM improvement_queue WHERE queue_id=?", (qid,)).fetchone()
    assert row["status"] == "pending", "catalog 側の見え方が変わったので戻してよい"


# ------------------------------------------------- 提案4: last_writer

def test_upsert_improvement_records_caller_module_in_last_writer():
    con = ps.connect(":memory:")
    ps.upsert_improvement(con, "tcg", "cert1", "catalog_add", source="auditor", ts="2026-09-04")
    row = con.execute("SELECT last_writer FROM improvement_queue WHERE item_id='cert1'").fetchone()
    assert "auditor" in row["last_writer"]
    assert "test_pdca_resolver_drop" in row["last_writer"]


def test_last_writer_updates_to_latest_caller_on_reupsert():
    con = ps.connect(":memory:")
    ps.upsert_improvement(con, "tcg", "cert1", "catalog_add", source="auditor", ts="2026-09-04")
    row1 = con.execute("SELECT last_writer FROM improvement_queue WHERE item_id='cert1'").fetchone()

    other_mod.call_upsert(con, "2026-09-04")
    row2 = con.execute("SELECT last_writer FROM improvement_queue WHERE item_id='cert1'").fetchone()

    assert row1["last_writer"] != row2["last_writer"]
    assert "helper_last_writer_other_module_20260904" in row2["last_writer"]


def test_queue_resolver_drop_writes_own_filename_to_last_writer():
    con = ps.connect(":memory:")
    qid = acr._queue_resolver_drop(
        "one_piece_tcg", "155040105", "model text", "REVIEW", "ST17-004_p1", con=con)
    row = con.execute("SELECT last_writer FROM improvement_queue WHERE queue_id=?",
                      (qid,)).fetchone()
    assert "auto_catalog_add_request" in row["last_writer"]
