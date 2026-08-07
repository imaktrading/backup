# -*- coding: utf-8 -*-
"""PDCA identity resolution gap 回帰テスト (2026-07-31).

Advisor 依頼 `2026-07-27_pdca_identity_resolution_gap.md` の (i)(ii):
  (i)  csv_auditor._resolve_identity: identity_by_sku 空でも sku=PSA10-<cert> なら
       PSA cache から Brand/Subject/CardNumber を組んで identity を backfill する。
       CSV 除外された cert に対して Catalog 依頼が identity=(不明) で永久再発する事故の根治。
  (ii) pdca_store.parse_missing_model_identity: post_psa_review が書く missing_models.csv の
       `cert{N} {BRAND} [{SUBJECT}] #{CARDNUMBER}` 書式から identity を parse する。
       素材が model 列に既にあるのに identity を渡していなかった経路 B の穴を塞ぐ。
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))


# ----- (i) csv_auditor._resolve_identity + _identity_from_psa_cache -----

def test_identity_from_psa_cache_reads_brand_subject_cardnumber(tmp_path, monkeypatch):
    import csv_auditor as ca
    # 一時 PSA cache dir を注入
    fake_dir = tmp_path / "psa_certs"
    fake_dir.mkdir()
    cert = "152976768"
    (fake_dir / f"{cert}.json").write_text(json.dumps({
        "CardNumber": "051",
        "Subject": "BOA HANCOCK",
        "Brand": "ONE PIECE JAPANESE OP07-500 YEARS IN THE FUTURE",
    }), encoding="utf-8")
    monkeypatch.setattr(ca, "_PSA_CACHE_DIR", str(fake_dir))
    ident = ca._identity_from_psa_cache(cert)
    assert "051" in ident
    assert "BOA HANCOCK" in ident
    assert "OP07" in ident


def test_identity_from_psa_cache_missing_returns_empty(tmp_path, monkeypatch):
    """cache file なし → 空文字列 (fail-safe、既存 identity を潰さない)。"""
    import csv_auditor as ca
    fake_dir = tmp_path / "no_such"
    fake_dir.mkdir()
    monkeypatch.setattr(ca, "_PSA_CACHE_DIR", str(fake_dir))
    assert ca._identity_from_psa_cache("99999999") == ""


def test_identity_from_psa_cache_malformed_json_returns_empty(tmp_path, monkeypatch):
    import csv_auditor as ca
    fake_dir = tmp_path / "psa_certs"
    fake_dir.mkdir()
    (fake_dir / "111.json").write_text("{not-json", encoding="utf-8")
    monkeypatch.setattr(ca, "_PSA_CACHE_DIR", str(fake_dir))
    assert ca._identity_from_psa_cache("111") == ""


def test_resolve_identity_prefers_by_sku_over_cache(tmp_path, monkeypatch):
    """identity_by_sku に値が入ってれば PSA cache を叩かず既存を返す (per-row 精度優先)。"""
    import csv_auditor as ca
    monkeypatch.setattr(ca, "_PSA_CACHE_DIR", str(tmp_path))   # fake path
    got = ca._resolve_identity("PSA10-152976768",
                               {"PSA10-152976768": "051 | BOA HANCOCK | OP07"})
    assert got == "051 | BOA HANCOCK | OP07"


def test_resolve_identity_falls_back_to_cache_for_missing_sku(tmp_path, monkeypatch):
    """CSV除外された cert (identity_by_sku 未登録) は cache backfill が働く。"""
    import csv_auditor as ca
    fake_dir = tmp_path / "psa_certs"
    fake_dir.mkdir()
    (fake_dir / "158452544.json").write_text(json.dumps({
        "CardNumber": "003", "Subject": "SON GOKU", "Brand": "SUPER DRAGON BALL HEROES",
    }), encoding="utf-8")
    monkeypatch.setattr(ca, "_PSA_CACHE_DIR", str(fake_dir))
    got = ca._resolve_identity("PSA10-158452544", {})
    assert "003" in got and "SON GOKU" in got


def test_resolve_identity_non_psa_sku_returns_empty(tmp_path, monkeypatch):
    """非 PSA sku (m....) は PSA cache 対象外。

    2026-08-01 改訂: PSA cache の次に **出品CSV履歴** を見るようになったので、
    「空になる」条件は *履歴にも無い* 場合。履歴にあれば解決するのが正しい挙動
    (メルカリ出品の identity はここでしか取れない)。
    """
    import csv_auditor as ca
    monkeypatch.setattr(ca, "_PSA_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(ca, "_CSV_HISTORY_IDENTITIES", {})     # 履歴 空
    assert ca._resolve_identity("m27764156929", {}) == ""


# ----- (ii) pdca_store.parse_missing_model_identity -----

def test_parse_missing_model_identity_standard_format():
    import pdca_store as ps
    m = "cert158452571 DRAGON BALL SUPER DIVERS 4 [SON GOKU EXTRA] #003 (auto候補=該当なし 要調査)"
    ident = ps.parse_missing_model_identity(m)
    assert "003" in ident
    assert "SON GOKU EXTRA" in ident
    assert "DRAGON BALL SUPER DIVERS 4" in ident
    # 順序: CARDNUMBER | SUBJECT | BRAND
    parts = ident.split(" | ")
    assert parts[0] == "003"
    assert parts[1] == "SON GOKU EXTRA"


def test_parse_missing_model_identity_one_piece_case():
    """Advisor が挙げた実例 (queue_id 540 の書式) を固定。"""
    import pdca_store as ps
    m = "cert168231144 ONE PIECE JAPANESE CHINA 2ND ANNIVERSARY SET [BOA HANCOCK] #051 (auto候補=該当なし 要調査)"
    ident = ps.parse_missing_model_identity(m)
    assert ident.startswith("051 | BOA HANCOCK |")
    assert "CHINA 2ND ANNIVERSARY" in ident


def test_parse_missing_model_identity_no_match_returns_empty():
    import pdca_store as ps
    # 書式が違う (model 列に自由文字列) → 空 (fail-safe)
    assert ps.parse_missing_model_identity("GA-2100-1AJF") == ""
    assert ps.parse_missing_model_identity("") == ""
    assert ps.parse_missing_model_identity(None) == ""


def test_parse_missing_model_identity_truncates_at_120():
    """長すぎる model でも identity は 120 字で truncate される (Catalog 依頼列幅ガード)。"""
    import pdca_store as ps
    long_brand = "ONE PIECE JAPANESE " + "X" * 200
    m = f"cert12345 {long_brand} [SUBJECT LONG] #099 (auto...)"
    ident = ps.parse_missing_model_identity(m)
    assert len(ident) <= 120
    assert ident.startswith("099 | SUBJECT LONG |")


def test_import_missing_models_passes_identity_to_upsert(tmp_path):
    """import_missing_models 経由で identity が queue に反映されること (E2E 経路 B)。"""
    import pdca_store as ps
    # tmp DB + tmp missing_models.csv を用意
    db = tmp_path / "pdca.db"
    csv = tmp_path / "missing_models.csv"
    csv.write_text(
        "category,model,detected_at\n"
        "one_piece_tcg,cert168231144 ONE PIECE JAPANESE CHINA 2ND ANNIVERSARY SET [BOA HANCOCK] #051 (auto),2026-07-30\n",
        encoding="utf-8")
    con = ps.connect(str(db))
    n = ps.import_missing_models(con, str(csv), ts="2026-07-31")
    assert n == 1
    row = con.execute("SELECT identity FROM improvement_queue LIMIT 1").fetchone()
    assert row is not None
    ident = row["identity"] or ""
    # queue の identity が空でないこと (経路 B の穴が塞がれた回帰)
    assert "051" in ident
    assert "BOA HANCOCK" in ident
    con.close()
