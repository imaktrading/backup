# -*- coding: utf-8 -*-
"""digest は pdca_accumulate (emit/prune) より前に読む (2026-09-01)。

何が起きていたか: `audit()` は `_pdca_accumulate` → digest の順で呼んでいた。
`_pdca_accumulate` 内の `emit_consolidated_request` が `verify_fn` で「catalog で引ける
= 解決済」と判定した pending 行を、発行直前に status='done' へ落とす。digest が
その**後**に `_load_pdca_recurring()` (WHERE status='pending') を読むため、同日中に
emit が閉じた再発行は recurring_missing に一度も載らなかった
(queue 610: seen_count 234 / seen_days 5 なのに digest は毎日 recurring_missing=0)。

直し方: digest 生成 (`_load_pdca_recurring` 呼び出し) を `_pdca_accumulate` より
**前**に読む (csv_auditor.py の audit() 内で呼び出し順を入れ替え)。
出典: hq/requests/2026-09-01_act_code_proposals_tcg_response.md 提案1
"""
import inspect
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(_HERE, "..", "tools")))

import csv_auditor as ca      # noqa: E402
import pdca_store as ps       # noqa: E402


def _seed_recurring_pending_row(con):
    """seen_days>=2 の pending 行を1本仕込む (= digest 対象の再発行)。"""
    qid = ps.upsert_improvement(con, "one_piece_tcg", "cert155040105", "catalog_add", "",
                                evidence="resolver=REVIEW", source="auditor", layer="A",
                                finding_type="catalog_gap", ts="2026-08-27")
    ps.upsert_improvement(con, "one_piece_tcg", "cert155040105", "catalog_add", "",
                          evidence="resolver=REVIEW", source="auditor", layer="A",
                          finding_type="catalog_gap", ts="2026-09-01")
    return qid


def test_audit_reads_digest_before_pdca_accumulate_in_source():
    """呼び出し順そのものを固定するリグレッションガード (audit() のソース行順)。"""
    src, start_line = inspect.getsourcelines(ca.audit)
    load_recurring_line = next(
        i for i, l in enumerate(src) if "_load_pdca_recurring()" in l)
    accumulate_line = next(
        i for i, l in enumerate(src) if l.strip().startswith("_pdca_accumulate("))
    assert load_recurring_line < accumulate_line, (
        "digest (_load_pdca_recurring) は _pdca_accumulate より前に呼ぶこと。"
        "後に呼ぶと、同日中に emit/prune が done にした再発行が digest から消える")


def test_recurring_row_survives_if_read_before_done_flip(tmp_path):
    """emit の done 化より先に読めば、その日閉じた再発行も digest に残る (直した後の姿)。"""
    db = str(tmp_path / "pdca.db")
    con = ps.connect(db)
    qid = _seed_recurring_pending_row(con)
    con.commit()

    # digest を先に読む (= 修正後の順序)
    rows = con.execute(
        "SELECT category,item_id,target_field,finding_type,seen_count,seen_days,status "
        "FROM improvement_queue WHERE status='pending' AND seen_days>=2").fetchall()
    recurring = ca.recurring_findings(
        [{"category": r["category"], "item_id": r["item_id"], "target_field": r["target_field"],
          "finding_type": r["finding_type"], "seen_count": r["seen_count"],
          "seen_days": r["seen_days"], "status": r["status"]} for r in rows])
    assert [r["item_id"] for r in recurring] == ["cert155040105"]

    # emit 相当: verify_fn が「catalog で引ける」と判定して done に落とす
    ps.set_status(con, qid, "done", ts="2026-09-01")
    con.commit()
    con.close()


def test_recurring_row_lost_if_read_after_done_flip(tmp_path):
    """(誤った旧順序の再現) done 化の後に読むと、同日閉じた再発行は digest から消える。"""
    db = str(tmp_path / "pdca.db")
    con = ps.connect(db)
    qid = _seed_recurring_pending_row(con)
    con.commit()

    # emit 相当を先に実行 (= 修正前の順序を再現)
    ps.set_status(con, qid, "done", ts="2026-09-01")
    con.commit()

    rows = con.execute(
        "SELECT category,item_id,target_field,finding_type,seen_count,seen_days,status "
        "FROM improvement_queue WHERE status='pending' AND seen_days>=2").fetchall()
    recurring = ca.recurring_findings(
        [{"category": r["category"], "item_id": r["item_id"], "target_field": r["target_field"],
          "finding_type": r["finding_type"], "seen_count": r["seen_count"],
          "seen_days": r["seen_days"], "status": r["status"]} for r in rows])
    assert recurring == [], "旧順序では done に落ちた行が digest から消える (再現できて正しい)"
    con.close()
