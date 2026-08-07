"""PDCA改善キューに card identity を載せる回帰テスト (2026-07-16)。

背景: 依頼キューが item_id (m*/PSA10-* = 出品ID) だけを Catalog に渡していたため、
Catalog は「それが何のカードか」を解決できず backfill 不能 → 同じ依頼が永久に再掲
(層A 60件が毎回そのまま = 再発ループ)。CSV 行には catalog 由来の事実が載っているので、
identity として同送する。
"""
import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

import csv_auditor                      # noqa: E402
import pdca_store                       # noqa: E402

HEADERS = ["CustomLabel", "*Title", "C:Game", "C:Set", "C:Card Name", "C:Card Number", "C:Rarity"]
ROW = ["PSA10-146618397", "PSA 10 One Piece Japanese Kingdoms of Intrigue #OP04-119",
       "One Piece CCG", "Kingdoms of Intrigue", "Donquixote Rosinante", "OP04-119", ""]


# ---- card_identity (純関数) ----
def test_identity_from_catalog_fields():
    got = csv_auditor.card_identity(HEADERS, ROW)
    assert "OP04-119" in got and "Donquixote Rosinante" in got and "Kingdoms of Intrigue" in got
    assert "PSA10-146618397" not in got          # 出品IDは identity ではない


def test_identity_dedups_repeated_values():
    """C:Card Name と C:Character が同値でも 1 回だけ (実CSVの常態)。"""
    h = HEADERS + ["C:Character"]
    got = csv_auditor.card_identity(h, ROW + ["Donquixote Rosinante"])
    assert got.count("Donquixote Rosinante") == 1


def test_identity_falls_back_to_title_when_specs_empty():
    row = ["m16798291085", "PSA 10 Pikachu Promo", "", "", "", "", ""]
    assert csv_auditor.card_identity(HEADERS, row) == "PSA 10 Pikachu Promo"


def test_identity_empty_when_no_clue():
    assert csv_auditor.card_identity(HEADERS, ["m1", "", "", "", "", "", ""]) == ""


def test_identity_never_fabricates_and_is_capped():
    """CSV に無い値を作らない + 長さ上限。"""
    got = csv_auditor.card_identity(HEADERS, ROW, max_len=12)
    assert len(got) <= 12
    assert got in "OP04-119 | Donquixote Rosinante | Kingdoms of Intrigue | One Piece CCG"


def test_identity_generic_across_categories():
    """カテゴリ別 if 無しで G-shock 等でも効く (列の有無だけで拾う)。"""
    h = ["CustomLabel", "C:Brand", "C:Model"]
    assert csv_auditor.card_identity(h, ["x", "Casio", "GA-2100-1A1"]) == "Casio | GA-2100-1A1"


# ---- 蓄積層 ----
@pytest.fixture()
def con():
    c = pdca_store.connect(":memory:")
    yield c
    c.close()


def test_upsert_stores_identity(con):
    pdca_store.upsert_improvement(con, "tcg", "m123", "C:Rarity",
                                  identity="OP04-119 | Rosinante", ts="2026-07-16")
    row = con.execute("SELECT identity FROM improvement_queue").fetchone()
    assert row["identity"] == "OP04-119 | Rosinante"


def test_reupsert_backfills_identity_into_existing_row(con):
    """identity 抜きで作られた既存60件が、次の監査で埋まる (作り直し不要)。"""
    pdca_store.upsert_improvement(con, "tcg", "m123", "C:Rarity", ts="2026-07-15")
    pdca_store.upsert_improvement(con, "tcg", "m123", "C:Rarity",
                                  identity="OP04-119 | Rosinante", ts="2026-07-16")
    rows = con.execute("SELECT identity, seen_count FROM improvement_queue").fetchall()
    assert len(rows) == 1                        # dedup_key に identity を含めない = 行が増えない
    assert rows[0]["identity"] == "OP04-119 | Rosinante"
    assert rows[0]["seen_count"] == 2            # 再発カウントは従来どおり


def test_empty_identity_does_not_wipe_existing(con):
    """identity 取得失敗時に既存の手掛かりを空で潰さない (fail-closed)。"""
    pdca_store.upsert_improvement(con, "tcg", "m123", "C:Rarity", identity="OP04-119", ts="2026-07-15")
    pdca_store.upsert_improvement(con, "tcg", "m123", "C:Rarity", identity="", ts="2026-07-16")
    assert con.execute("SELECT identity FROM improvement_queue").fetchone()["identity"] == "OP04-119"


def test_migration_adds_column_to_legacy_db(tmp_path):
    """identity 列の無い既存 pdca.db を作り直さず前進 (ALTER・冪等)。"""
    db = str(tmp_path / "legacy.db")
    raw = sqlite3.connect(db)
    raw.execute("CREATE TABLE improvement_queue (queue_id INTEGER PRIMARY KEY AUTOINCREMENT,"
                " dkey TEXT UNIQUE, category TEXT, item_id TEXT, target_field TEXT,"
                " suggested_value TEXT, evidence TEXT, source TEXT, layer TEXT, confidence REAL,"
                " finding_type TEXT, seen_count INTEGER DEFAULT 1, priority REAL,"
                " status TEXT DEFAULT 'pending', created_ts TEXT, updated_ts TEXT, reviewed_ts TEXT)")
    raw.execute("INSERT INTO improvement_queue (dkey, category, item_id, target_field, status)"
                " VALUES ('tcg|m123|C:Rarity|', 'tcg', 'm123', 'C:Rarity', 'pending')")
    raw.commit()
    raw.close()

    c = pdca_store.connect(db)
    assert "identity" in {r[1] for r in c.execute("PRAGMA table_info(improvement_queue)")}
    pdca_store.upsert_improvement(c, "tcg", "m123", "C:Rarity", identity="OP04-119", ts="2026-07-16")
    assert c.execute("SELECT identity FROM improvement_queue").fetchone()["identity"] == "OP04-119"
    c.close()
    pdca_store.connect(db).close()               # 2回目の connect でも ALTER が壊れない (冪等)


def test_emitted_request_md_carries_identity(con, tmp_path):
    """Catalog が読む面 = 依頼 .md に identity が出る (これが無いと backfill 不能)。"""
    pdca_store.upsert_improvement(con, "tcg", "m16798291085", "C:Rarity",
                                  identity="OP04-119 | Rosinante | Kingdoms of Intrigue",
                                  finding_type="必須Item Specific", ts="2026-07-16")
    n = pdca_store.emit_consolidated_request(con, "tcg", str(tmp_path), "2026-07-16")
    assert n == 1
    text = (tmp_path / "2026-07-16_pdca_catalog_queue_tcg.md").read_text(encoding="utf-8")
    assert "OP04-119 | Rosinante | Kingdoms of Intrigue" in text
    assert "商品(identity)" in text


def test_emitted_request_md_flags_unknown_identity(con, tmp_path):
    """identity 不明は「解決済」に見せず、要調査として明示 (silent drop 禁止)。"""
    pdca_store.upsert_improvement(con, "tcg", "m999", "C:Set", ts="2026-07-16")
    pdca_store.emit_consolidated_request(con, "tcg", str(tmp_path), "2026-07-16")
    text = (tmp_path / "2026-07-16_pdca_catalog_queue_tcg.md").read_text(encoding="utf-8")
    assert "(不明=要調査)" in text
