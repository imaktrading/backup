# -*- coding: utf-8 -*-
"""identity 未解決行の扱い 回帰テスト (2026-08-01)。

Advisor 依頼 `2026-07-27_pdca_identity_resolution_gap.md` の §3/§4 は 7/31 時点で **未実装**
だった (§2 の解決経路だけ入っていた):
  (2) identity 未解決の行を Catalog へ送らない  → partition_by_identity / emit_consolidated_request
  (3) 送らなかった分を毎回 全件 再掲            → write_unresolved_note
  (+) 既に積まれた行の identity 後埋め           → backfill_identities

★ gshock の item_id は型番そのもの (= それだけで特定可能) なので held に落とさない。
   ここを取り違えると gshock の catalog 依頼が丸ごと silent drop される。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

import pdca_store as ps


# ----- is_opaque_listing_id (純関数) -----

def test_opaque_ids_are_listing_ids_only():
    assert ps.is_opaque_listing_id("PSA10-152976768")
    assert ps.is_opaque_listing_id("m63215518361")


def test_gshock_model_and_program_signature_are_not_opaque():
    """型番 / 症状シグネチャは Catalog へ送り続ける (既存経路を塞がない)。"""
    assert not ps.is_opaque_listing_id("GA-2100-1A1JF")
    assert not ps.is_opaque_listing_id("MTG-B3000B-1AJF")
    assert not ps.is_opaque_listing_id("program:title_len_over")
    assert not ps.is_opaque_listing_id("")
    assert not ps.is_opaque_listing_id(None)


def test_short_m_number_is_not_treated_as_mercari_id():
    """m + 短い数字は型番の可能性がある → 落とさない (fail-safe)。"""
    assert not ps.is_opaque_listing_id("m1234")


# ----- partition_by_identity (純関数) -----

def _row(item_id, identity="", category="tcg", field="C:Rarity"):
    return {"item_id": item_id, "identity": identity, "category": category,
            "target_field": field, "evidence": "必須Item Specific", "seen_count": 1}


def test_partition_holds_only_unresolved_listing_ids():
    items = [
        _row("PSA10-152976768"),                       # 出品ID + identity 空 → 保留
        _row("m63215518361"),                          # 同上
        _row("PSA10-158452544", "FB08-121 | SON GOTEN"),  # identity 有 → 送る
        _row("GA-2100-1A1JF", category="gshock"),      # 型番 → identity 無くても送る
    ]
    sendable, held = ps.partition_by_identity(items)
    assert [r["item_id"] for r in held] == ["PSA10-152976768", "m63215518361"]
    assert [r["item_id"] for r in sendable] == ["PSA10-158452544", "GA-2100-1A1JF"]


def test_partition_treats_whitespace_identity_as_empty():
    sendable, held = ps.partition_by_identity([_row("PSA10-1", "   ")])
    assert not sendable and len(held) == 1


# ----- backfill_identities (DB) -----

def _con(tmp_path):
    return ps.connect(str(tmp_path / "pdca.db"))


def test_backfill_fills_empty_identity_only(tmp_path):
    con = _con(tmp_path)
    ps.upsert_improvement(con, "tcg", "PSA10-111", "C:Rarity", source="auditor", ts="2026-08-01")
    ps.upsert_improvement(con, "tcg", "PSA10-222", "C:Set", identity="既存値",
                          source="auditor", ts="2026-08-01")
    res = ps.backfill_identities(con, lambda iid: "解決:" + iid, ts="2026-08-01")
    assert res == {"filled": 1, "checked": 1}
    got = {r["item_id"]: r["identity"] for r in ps.list_queue(con)}
    assert got["PSA10-111"] == "解決:PSA10-111"
    assert got["PSA10-222"] == "既存値"          # 既存を上書きしない


def test_backfill_survives_resolver_exception(tmp_path):
    """解決器が飛んでも監査を止めない (write-only 原則)。"""
    con = _con(tmp_path)
    ps.upsert_improvement(con, "tcg", "PSA10-333", "C:Rarity", source="auditor", ts="2026-08-01")

    def boom(_iid):
        raise RuntimeError("psa cache 破損")

    assert ps.backfill_identities(con, boom, ts="2026-08-01")["filled"] == 0


# ----- emit_consolidated_request (DB + ファイル) -----

def test_emit_excludes_unresolved_and_reports_them(tmp_path):
    con = _con(tmp_path)
    ps.upsert_improvement(con, "tcg", "PSA10-444", "C:Rarity", source="auditor", ts="2026-08-01")
    ps.upsert_improvement(con, "tcg", "PSA10-555", "C:Set", identity="OP07-051 | BOA HANCOCK",
                          source="auditor", ts="2026-08-01")
    held = []
    out = tmp_path / "req"
    n = ps.emit_consolidated_request(con, "tcg", str(out), "2026-08-01", held_out=held)
    body = (out / "2026-08-01_pdca_catalog_queue_tcg.md").read_text(encoding="utf-8")
    assert n == 1                                  # 送ったのは identity 有の 1 件だけ
    assert "PSA10-555" in body
    assert "PSA10-444" not in body                 # 着手不能な行は送らない
    assert [r["item_id"] for r in held] == ["PSA10-444"]


def test_emit_writes_nothing_when_all_rows_are_held(tmp_path):
    con = _con(tmp_path)
    ps.upsert_improvement(con, "tcg", "PSA10-666", "C:Rarity", source="auditor", ts="2026-08-01")
    held = []
    out = tmp_path / "req"
    assert ps.emit_consolidated_request(con, "tcg", str(out), "2026-08-01", held_out=held) == 0
    assert not (out / "2026-08-01_pdca_catalog_queue_tcg.md").exists()
    assert len(held) == 1


# ----- write_unresolved_note -----

def test_unresolved_note_lists_every_held_row(tmp_path):
    p = tmp_path / "logs" / "pdca_identity_unresolved.md"
    n = ps.write_unresolved_note([_row("PSA10-777"), _row("m88888888888")], str(p),
                                 "2026-08-01", category="tcg")
    txt = p.read_text(encoding="utf-8")
    assert n == 2
    assert "未解決 2 件" in txt
    assert "PSA10-777" in txt and "m88888888888" in txt


def test_unresolved_note_written_even_when_zero(tmp_path):
    """0件でもファイルを残す = 「見に行けば必ず現状が読める」(状態の消失を作らない)。"""
    p = tmp_path / "pdca_identity_unresolved.md"
    assert ps.write_unresolved_note([], str(p), "2026-08-01", category="gshock") == 0
    assert "未解決 0 件" in p.read_text(encoding="utf-8")
