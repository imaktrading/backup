# -*- coding: utf-8 -*-
"""まとめ依頼が閉じない/増殖する/台帳が腐る の3件 (2026-09-06)。

依頼書: hq/requests/2026-09-06_act_code_proposals_tcg.md 提案1・2(出口)・3
回答書: hq/requests/2026-09-06_act_code_proposals_tcg_response.md
"""
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(_HERE, "..", "tools")))

import pdca_store as pdca  # noqa: E402


def _mem_con():
    return pdca.connect(":memory:")


# ------------------------------------------------- 提案1: まとめ依頼が閉じない

def test_emit_consolidated_request_writes_queue_id_sidecar(tmp_path):
    con = _mem_con()
    qid = pdca.upsert_improvement(con, "tcg", "cert1 A B", "catalog_add", "",
                                  source="missing_models", layer="A",
                                  finding_type="catalog_gap", ts="2026-09-06")
    pdca.emit_consolidated_request(con, "tcg", str(tmp_path), "2026-09-06")
    side = tmp_path / "2026-09-06_pdca_catalog_queue_tcg.queue_ids.json"
    assert side.is_file(), "queue_id sidecar が書かれていない"
    assert json.loads(side.read_text(encoding="utf-8")) == [qid]


def test_sync_processed_closes_consolidated_request_via_sidecar(tmp_path):
    """まとめ依頼は topic==item_id が一致しないので、sidecar が無いと0件しか閉じない。"""
    con = _mem_con()
    qid = pdca.upsert_improvement(con, "tcg", "cert1 A B", "catalog_add", "",
                                  source="missing_models", layer="A",
                                  finding_type="catalog_gap", ts="2026-09-06")
    pdca.emit_consolidated_request(con, "tcg", str(tmp_path), "2026-09-06")
    # Catalog が答えた → ファイルを processed にリネーム (中身はここでは問わない)
    (tmp_path / "2026-09-06_pdca_catalog_queue_tcg.md").rename(
        tmp_path / "2026-09-06_pdca_catalog_queue_tcg_processed.md")
    synced = pdca.sync_processed(con, str(tmp_path), ts="2026-09-07")
    assert synced == 1
    row = con.execute("SELECT status FROM improvement_queue WHERE queue_id=?", (qid,)).fetchone()
    assert row["status"] == "done"


def test_sync_processed_without_sidecar_still_closes_per_item_requests():
    """per-item 依頼 (topic=item_id) は従来どおり sidecar 無しで閉じる (既存経路を壊さない)。"""
    import tempfile
    con = _mem_con()
    qid = pdca.upsert_improvement(con, "tcg", "cert999", "catalog_add", "",
                                  source="missing_models", layer="A",
                                  finding_type="catalog_gap", ts="2026-09-06")
    with tempfile.TemporaryDirectory() as d:
        (open(os.path.join(d, "2026-09-06_cert999_processed.md"), "w")).close()
        synced = pdca.sync_processed(con, d, ts="2026-09-07")
    assert synced == 1
    row = con.execute("SELECT status FROM improvement_queue WHERE queue_id=?", (qid,)).fetchone()
    assert row["status"] == "done"


# ------------------------------------------------- 提案2(出口): 番号不明は resolver_gap へ

def test_prune_marks_unreadable_number_missing_row_as_resolver_gap():
    con = _mem_con()
    qid = pdca.upsert_improvement(con, "one_piece_tcg",
                                  "番号不明 【PSA10】 シャンクス OP09 001 (捨てた仕入候補の目視)",
                                  "catalog_add", "", source="missing_models", layer="A",
                                  finding_type="catalog_gap", ts="2026-09-05")
    res = pdca.prune_resolved_gaps(con, lambda cat, iid, hints="": False, ts="2026-09-06")
    assert res["resolver_gap"] == 1
    row = con.execute("SELECT status FROM improvement_queue WHERE queue_id=?", (qid,)).fetchone()
    assert row["status"] == "resolver_gap"


def test_prune_does_not_gap_normal_unresolved_rows():
    """番号不明 marker が無い普通の未解決行は、従来どおり pending のまま残る。"""
    con = _mem_con()
    pdca.upsert_improvement(con, "tcg", "WEIRD-UNRESOLVED-XYZ", "catalog_add", "",
                            source="missing_models", layer="A",
                            finding_type="catalog_gap", ts="2026-09-05")
    res = pdca.prune_resolved_gaps(con, lambda cat, iid, hints="": False, ts="2026-09-06")
    assert res["resolver_gap"] == 0
    pend = {r["item_id"] for r in pdca.list_queue(con, status="pending")}
    assert "WEIRD-UNRESOLVED-XYZ" in pend


def test_prune_resolver_gap_removes_row_from_consolidated_request(tmp_path):
    """resolver_gap は status='pending' ではなくなるので、まとめ依頼(層A)から自然に外れる。"""
    con = _mem_con()
    pdca.upsert_improvement(con, "tcg", "番号不明 X", "catalog_add", "",
                            source="missing_models", layer="A",
                            finding_type="catalog_gap", ts="2026-09-05")
    pdca.prune_resolved_gaps(con, lambda cat, iid, hints="": False, ts="2026-09-06")
    n = pdca.emit_consolidated_request(con, "tcg", str(tmp_path), "2026-09-06")
    assert n == 0
    assert not (tmp_path / "2026-09-06_pdca_catalog_queue_tcg.md").exists()


def test_prune_exception_does_not_gap_unreadable_row():
    """resolve_fn が例外を吐いた時は fail-closed = 触らない(resolver_gap にもしない)。"""
    con = _mem_con()
    qid = pdca.upsert_improvement(con, "tcg", "番号不明 X", "catalog_add", "",
                                  source="missing_models", layer="A",
                                  finding_type="catalog_gap", ts="2026-09-05")
    def _boom(cat, iid, hints=""):
        raise RuntimeError("down")
    res = pdca.prune_resolved_gaps(con, _boom, ts="2026-09-06")
    assert res["resolver_gap"] == 0
    row = con.execute("SELECT status FROM improvement_queue WHERE queue_id=?", (qid,)).fetchone()
    assert row["status"] == "pending"


# ------------------------------------------------- 提案3: category訂正が新規行を作る

def test_category_correction_updates_existing_row_instead_of_creating_new():
    con = _mem_con()
    qid = pdca.upsert_improvement(con, "one_piece_tcg", "番号不明 キラヤマト", "catalog_add", "",
                                  source="missing_models", layer="A",
                                  finding_type="catalog_gap", ts="2026-09-05")
    qid2 = pdca.upsert_improvement(con, "gundam_tcg", "番号不明 キラヤマト", "catalog_add", "",
                                   source="missing_models", layer="A",
                                   finding_type="catalog_gap", ts="2026-09-06")
    assert qid2 == qid, "category を直しただけなのに新規行になった"
    rows = con.execute("SELECT category, dkey FROM improvement_queue WHERE queue_id=?",
                       (qid,)).fetchall()
    assert len(rows) == 1
    assert rows[0]["category"] == "gundam_tcg"
    assert rows[0]["dkey"] == pdca.dedup_key("gundam_tcg", "番号不明 キラヤマト", "catalog_add", "")


def test_category_correction_does_not_touch_done_rows():
    """訂正マッチは pending 行だけ (閉じた行を勝手に書き換えない)。"""
    con = _mem_con()
    qid = pdca.upsert_improvement(con, "one_piece_tcg", "X", "catalog_add", "",
                                  source="missing_models", layer="A",
                                  finding_type="catalog_gap", ts="2026-09-05")
    pdca.set_status(con, qid, "done", "2026-09-05")
    qid2 = pdca.upsert_improvement(con, "gundam_tcg", "X", "catalog_add", "",
                                   source="missing_models", layer="A",
                                   finding_type="catalog_gap", ts="2026-09-06")
    assert qid2 != qid
