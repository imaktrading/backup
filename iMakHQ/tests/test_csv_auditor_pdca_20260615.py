"""csv_auditor → pdca_store 連携テスト (PDCA spiral-up Phase1b+2・2026-06-15)。

固定: 監査の catalog 指摘が改善キューに蓄積され、dedup済 catalog 依頼が集約発行される。
DB/依頼dir は tmp に隔離。dry_run は記録しない。
"""
import os
import sys

_TOOLS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "tools"))
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import csv_auditor as A  # noqa: E402
import pdca_store as P   # noqa: E402


def test_pdca_accumulate_writes_queue_and_emits(tmp_path, monkeypatch):
    db = str(tmp_path / "pdca.db")
    reqdir = tmp_path / "requests"
    reqdir.mkdir()
    monkeypatch.setattr(P, "DB_PATH", db)
    monkeypatch.setattr(A, "CATALOG_REQ_DIR", str(reqdir))
    monkeypatch.setattr(A, "MISSING_MODELS_PATH", str(tmp_path / "no_missing.csv"))  # 隔離(空)

    catalog_items = [("S8b-241", "必須Item Specific 'C:Rarity' が空"),
                     ("VOLTORB", "iMakCatalog 未登録")]
    A._pdca_accumulate("tcg", catalog_items, [], dry_run=False)

    con = P.connect(db)
    rows = P.list_queue(con, status="pending")
    items = {r["item_id"]: r for r in rows}
    assert "S8b-241" in items and "VOLTORB" in items
    assert items["S8b-241"]["target_field"] == "C:Rarity"   # C:列をmsgから抽出
    # 集約 .md が発行されている
    emitted = list(reqdir.glob("*_pdca_catalog_queue_tcg.md"))
    assert len(emitted) == 1
    assert "S8b-241" in emitted[0].read_text(encoding="utf-8")


def test_import_missing_models_into_queue(tmp_path):
    # missing_models.csv (catalog未登録) が改善キューに層A catalog_gap として乗る
    mm = tmp_path / "missing_models.csv"
    mm.write_text("category,model,detected_at\n"
                  "pokemon_tcg,VOLTORB NATIONAL BEGINNING-014,2026-06-15\n"
                  "pokemon_tcg,VOLTORB NATIONAL BEGINNING-014,2026-06-15\n"  # 重複→dedup
                  "gundam_tcg,SOME GUNDAM-099,2026-06-15\n", encoding="utf-8")
    con = P.connect(":memory:")
    n = P.import_missing_models(con, str(mm), ts="2026-06-15")
    assert n == 3                                    # 3行読む
    rows = P.list_queue(con)
    items = {r["item_id"] for r in rows}
    assert items == {"VOLTORB NATIONAL BEGINNING-014", "SOME GUNDAM-099"}  # dedup で2件
    for r in rows:
        assert r["finding_type"] == "catalog_gap" and r["layer"] == "A"


def test_import_missing_models_no_file(tmp_path):
    con = P.connect(":memory:")
    assert P.import_missing_models(con, str(tmp_path / "nope.csv")) == 0


def test_pdca_accumulate_dry_run_noop(tmp_path, monkeypatch):
    db = str(tmp_path / "pdca.db")
    monkeypatch.setattr(P, "DB_PATH", db)
    monkeypatch.setattr(A, "CATALOG_REQ_DIR", str(tmp_path))
    A._pdca_accumulate("tcg", [("X", "必須 'C:Set' が空")], [], dry_run=True)
    # dry_run は DB を作らない/書かない
    assert not os.path.exists(db)


def test_pdca_accumulate_never_raises(monkeypatch):
    # pdca_store import 失敗等でも監査を壊さない (try/except)
    monkeypatch.setattr(P, "DB_PATH", "/nonexistent_dir_xyz/\x00bad/pdca.db")
    # 例外を投げずに戻ること (握りつぶし)
    A._pdca_accumulate("tcg", [("X", "必須 'C:Set' が空")], [], dry_run=False)
