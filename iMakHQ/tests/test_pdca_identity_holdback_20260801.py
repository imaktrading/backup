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


# ----- prune_non_applicable_specs (2026-08-01 追加) -----

def test_parse_identity_fields():
    assert ps.parse_identity_fields("E-60 | Energy Marker | Manga Booster 01") == ("E-60", "Energy Marker")
    assert ps.parse_identity_fields("RP-029") == ("RP-029", "")
    assert ps.parse_identity_fields("") == ("", "")
    assert ps.parse_identity_fields(None) == ("", "")


def test_prune_retires_specs_that_are_no_longer_required(tmp_path):
    """7/29-30 に「公式に存在しない」と確定した種別の残骸を退役させる。"""
    con = _con(tmp_path)
    ps.upsert_improvement(con, "tcg", "PSA10-1", "C:Rarity", identity="E-60 | Energy Marker | MB01",
                          finding_type="必須Item Specific", source="auditor", ts="2026-08-01")
    ps.upsert_improvement(con, "tcg", "PSA10-2", "C:Rarity", identity="101/184 | Umbreon VMAX | VMAX Climax",
                          finding_type="必須Item Specific", source="auditor", ts="2026-08-01")

    def still(num, name, field):
        return not (name.lower() == "energy marker" or num.lower().startswith("rp-"))

    assert ps.prune_non_applicable_specs(con, still, ts="2026-08-01") == {"pruned": 1, "checked": 2}
    st = {r["item_id"]: r["status"] for r in ps.list_queue(con)}
    assert st["PSA10-1"] == "resolved" and st["PSA10-2"] == "pending"


def test_prune_keeps_rows_without_identity_material(tmp_path):
    """identity が無い行は判定材料が無い = 触らない (誤退役より再掲の方が安全)。"""
    con = _con(tmp_path)
    ps.upsert_improvement(con, "tcg", "m99999999999", "C:Rarity",
                          finding_type="必須Item Specific", source="auditor", ts="2026-08-01")
    assert ps.prune_non_applicable_specs(con, lambda *a: False, ts="2026-08-01")["pruned"] == 0


def test_prune_keeps_rows_when_rule_raises(tmp_path):
    con = _con(tmp_path)
    ps.upsert_improvement(con, "tcg", "PSA10-3", "C:Rarity", identity="E-60 | Energy Marker",
                          finding_type="必須Item Specific", source="auditor", ts="2026-08-01")

    def boom(*_a):
        raise RuntimeError("check_csv import 不能")

    assert ps.prune_non_applicable_specs(con, boom, ts="2026-08-01")["pruned"] == 0


def test_prune_ignores_non_required_spec_findings(tmp_path):
    """catalog_gap 等 (必須spec以外) は対象外。"""
    con = _con(tmp_path)
    ps.upsert_improvement(con, "tcg", "PSA10-4", "catalog_request", identity="E-60 | Energy Marker",
                          finding_type="catalog_gap", source="auditor", ts="2026-08-01")
    assert ps.prune_non_applicable_specs(con, lambda *a: False, ts="2026-08-01")["checked"] == 0


def test_still_required_spec_uses_check_csv_ssot():
    """判定は check_csv (SSOT) 側。ここに除外表を複製していないことの確認。"""
    import csv_auditor as ca
    assert not ca._still_required_spec("E-60", "Energy Marker", "C:Rarity")
    assert not ca._still_required_spec("RP-029", "Resource", "C:Rarity")
    assert ca._still_required_spec("101/184", "Umbreon VMAX", "C:Rarity")
    assert ca._still_required_spec("101/184", "Umbreon VMAX", "program_fix")   # 必須リスト外


# ----- 出品CSV 履歴からの identity 復元 (2026-08-01: メルカリ出品の唯一の手掛かり) -----

def _write_csv(path, rows):
    import csv as _c
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = _c.writer(f)
        w.writerow(["CustomLabel", "C:Card Number", "C:Card Name", "C:Set"])
        for r in rows:
            w.writerow(r)


def test_csv_history_resolves_mercari_listing_id(tmp_path, monkeypatch):
    import csv_auditor as ca
    _write_csv(tmp_path / "tcg_upload_1.csv",
               [["m63215518361", "045/093", "Mewtwo-EX", "Black & White Ex Battle Boost"]])
    monkeypatch.setattr(ca, "_CSV_HISTORY_IDENTITIES", None)
    idx = ca._load_csv_history_identities(str(tmp_path))
    monkeypatch.setattr(ca, "_CSV_HISTORY_IDENTITIES", idx)
    got = ca._identity_from_csv_history("m63215518361")
    assert "045/093" in got and "Mewtwo-EX" in got


def test_csv_history_prefers_newest_file(tmp_path, monkeypatch):
    """同じ出品IDが複数CSVにあるなら新しい方 (= 最新の catalog 値)。"""
    import os as _os
    import csv_auditor as ca
    old, new = tmp_path / "a.csv", tmp_path / "b.csv"
    _write_csv(old, [["m1111", "OLD-1", "旧名", "旧セット"]])
    _write_csv(new, [["m1111", "NEW-1", "新名", "新セット"]])
    _os.utime(old, (1000, 1000))
    _os.utime(new, (2000, 2000))
    monkeypatch.setattr(ca, "_CSV_HISTORY_IDENTITIES", None)
    assert "NEW-1" in ca._load_csv_history_identities(str(tmp_path))["m1111"]


def test_csv_history_skips_broken_files(tmp_path, monkeypatch):
    """壊れた/列違いの CSV 1本で全体を落とさない。"""
    import csv_auditor as ca
    (tmp_path / "broken.csv").write_text("これは,CSVでは,ない", encoding="utf-8")
    _write_csv(tmp_path / "ok.csv", [["m2222", "OP01-013", "Sanji", ""]])
    monkeypatch.setattr(ca, "_CSV_HISTORY_IDENTITIES", None)
    assert "OP01-013" in ca._load_csv_history_identities(str(tmp_path))["m2222"]


def test_csv_history_returns_empty_for_unknown_sku(tmp_path, monkeypatch):
    import csv_auditor as ca
    _write_csv(tmp_path / "ok.csv", [["m3333", "OP01-013", "Sanji", ""]])
    monkeypatch.setattr(ca, "_CSV_HISTORY_IDENTITIES", None)
    idx = ca._load_csv_history_identities(str(tmp_path))
    monkeypatch.setattr(ca, "_CSV_HISTORY_IDENTITIES", idx)
    assert ca._identity_from_csv_history("m9999") == ""


def test_resolve_identity_order_is_by_sku_then_psa_then_csv(tmp_path, monkeypatch):
    """優先順: CSV行の値 > PSA cache > 出品CSV履歴 (精度の高い順)。"""
    import csv_auditor as ca
    monkeypatch.setattr(ca, "_PSA_CACHE_DIR", str(tmp_path / "no_psa"))
    monkeypatch.setattr(ca, "_CSV_HISTORY_IDENTITIES", {"PSA10-9": "履歴値", "m4444": "履歴値"})
    assert ca._resolve_identity("PSA10-9", {"PSA10-9": "行の値"}) == "行の値"
    assert ca._resolve_identity("PSA10-9", None) == "履歴値"      # PSA cache 無 → 履歴
    assert ca._resolve_identity("m4444", None) == "履歴値"
