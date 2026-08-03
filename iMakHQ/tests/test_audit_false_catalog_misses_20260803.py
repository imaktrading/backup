# -*- coding: utf-8 -*-
"""audit_false_catalog_misses.py 回帰テスト (2026-08-03).

依頼 `2026-08-03_psa_to_csv_false_catalog_miss_response.md` Q2 対応:
過去の auto_catalog_add 依頼書から「auto候補<PID>=該当なし」の false-miss
(実は catalog に PID が存在する) を検出する調査ツール。

保護対象:
  - 原本 md のみ拾い、`_processed.md` 等の rename copy を二重カウントしない
  - `auto候補<PID>` / `auto候補「<PID>` の表記揺れ両方を拾う
  - `auto候補無=` (候補すら無い) は no_candidate に分類
  - PID が products.sqlite に存在すれば false_miss、無ければ true_miss
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "tools")))
import audit_false_catalog_misses as afm


# --- fixtures ---------------------------------------------------------------

_ORIG_MD_BODY = """# 自動依頼: One Piece TCG カタログ追加 (auto-generated)

## 追加対象 (3 models)

| model | detected_at |
|---|---|
| `cert111111111 ONE PIECE JAPANESE PRB01-PREMIUM BOOSTER [MONKEY D. LUFFY ALTERNATE ART] #024 (auto候補OP01-024_PRB01=該当なし 要調査)` | 2026-08-03 01:00:00 |
| `cert222222222 ONE PIECE JAPANESE OP99 [DUMMY] #999 (auto候補OP99-999=該当なし 要調査)` | 2026-08-03 01:00:00 |
| `cert333333333 ONE PIECE JAPANESE OP99 [DUMMY] #001 (auto候補無=該当なし 要調査)` | 2026-08-03 01:00:00 |
"""

_PROCESSED_MD_BODY = """# 自動依頼: One Piece TCG カタログ追加 (auto-generated)

## 追加対象 (3 models)

| model | detected_at |
|---|---|
| `cert111111111 ONE PIECE JAPANESE PRB01-PREMIUM BOOSTER [MONKEY D. LUFFY ALTERNATE ART] #024 (auto候補OP01-024_PRB01=該当なし 要調査)` | 2026-08-03 01:00:00 |
"""

_BRACKET_MD_BODY = """# 自動依頼: Pokemon TCG カタログ追加

| model | detected_at |
|---|---|
| `cert444444444 POKEMON JAPANESE FOO [BAR] #123 (auto候補「S8a-P-022=該当なし 要調査)` | 2026-06-15 20:00:00 |
"""


def _seed(tmp_path: Path) -> Path:
    req = tmp_path / "requests"
    req.mkdir()
    (req / "2026-08-03_auto_catalog_add_one_piece_tcg.md").write_text(
        _ORIG_MD_BODY, encoding="utf-8")
    # 同じ日/カテゴリの processed copy — 原本と重複行を持つが二重カウント禁止
    (req / "2026-08-03_auto_catalog_add_one_piece_tcg_processed.md").write_text(
        _PROCESSED_MD_BODY, encoding="utf-8")
    # bracket 表記の別カテゴリ
    (req / "2026-06-15_auto_catalog_add_pokemon_tcg.md").write_text(
        _BRACKET_MD_BODY, encoding="utf-8")
    return req


def _seed_db(tmp_path: Path) -> Path:
    db = tmp_path / "products.sqlite"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE products ("
        "id INTEGER PRIMARY KEY, category TEXT NOT NULL, product_id TEXT NOT NULL,"
        "name TEXT NOT NULL, specs TEXT NOT NULL, source TEXT NOT NULL,"
        "created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
    )
    # 存在する PID (false-miss と判定されるべき)
    conn.execute(
        "INSERT INTO products(category,product_id,name,specs,source,created_at,updated_at)"
        " VALUES(?,?,?,?,?,?,?)",
        ("one_piece_tcg", "OP01-024_PRB01", "Luffy", "{}", "seed", "2026-01-01", "2026-01-01"),
    )
    conn.execute(
        "INSERT INTO products(category,product_id,name,specs,source,created_at,updated_at)"
        " VALUES(?,?,?,?,?,?,?)",
        ("pokemon_tcg", "S8a-P-022", "Mewtwo", "{}", "seed", "2026-01-01", "2026-01-01"),
    )
    conn.commit()
    conn.close()
    return db


# --- tests ------------------------------------------------------------------

def test_only_original_md_scanned_not_processed_copy(tmp_path):
    """`_processed.md` 等の rename copy を二重カウントしない."""
    req = _seed(tmp_path)
    rows = afm.scan_requests(req)
    certs = [r["cert"] for r in rows]
    # cert111111111 は原本と processed copy 両方に居るが 1 回だけ拾う
    assert certs.count("111111111") == 1
    # bracket 表記の cert444 も拾われている
    assert "444444444" in certs
    # 全体で 4 行 (3 原本 one_piece + 1 pokemon)
    assert len(rows) == 4


def test_bracket_variant_recognized(tmp_path):
    """`auto候補「PID=` の表記揺れも PID として拾う."""
    req = _seed(tmp_path)
    rows = afm.scan_requests(req)
    hit = [r for r in rows if r["cert"] == "444444444"]
    assert len(hit) == 1
    assert hit[0]["pid"] == "S8a-P-022"
    assert hit[0]["category"] == "pokemon_tcg"


def test_no_candidate_bucket(tmp_path):
    """`auto候補無=` は no_candidate に分類され false-miss にカウントされない."""
    req = _seed(tmp_path)
    db = _seed_db(tmp_path)
    rows = afm.scan_requests(req)
    conn = sqlite3.connect(str(db))
    try:
        cls = afm.classify(rows, conn)
    finally:
        conn.close()
    assert any(r["cert"] == "333333333" for r in cls["no_candidate"])
    assert not any(r["cert"] == "333333333" for r in cls["false_miss"])
    assert not any(r["cert"] == "333333333" for r in cls["true_miss"])


def test_false_miss_detected_when_pid_exists(tmp_path):
    """PID が products.sqlite に存在すれば false_miss."""
    req = _seed(tmp_path)
    db = _seed_db(tmp_path)
    rows = afm.scan_requests(req)
    conn = sqlite3.connect(str(db))
    try:
        cls = afm.classify(rows, conn)
    finally:
        conn.close()
    false_certs = {r["cert"] for r in cls["false_miss"]}
    # 111 (OP01-024_PRB01) と 444 (S8a-P-022) は false-miss
    assert false_certs == {"111111111", "444444444"}
    # 222 (OP99-999) は catalog に無い → true_miss
    assert {r["cert"] for r in cls["true_miss"]} == {"222222222"}


def test_summary_percentage_excludes_no_candidate(tmp_path):
    """false_miss% は with_candidate (=候補あり) を分母にする (無 は除外)."""
    req = _seed(tmp_path)
    db = _seed_db(tmp_path)
    rows = afm.scan_requests(req)
    conn = sqlite3.connect(str(db))
    try:
        summary = afm.summarize(afm.classify(rows, conn))
    finally:
        conn.close()
    # with_candidate=3 (111, 222, 444) / false_miss=2 (111, 444) → 66.67%
    assert summary["with_candidate"] == 3
    assert summary["no_candidate"] == 1
    assert summary["false_miss"] == 2
    assert summary["true_miss"] == 1
    assert summary["false_miss_pct_of_with_candidate"] == 66.67


def test_category_scoping_prevents_cross_category_false_positive(tmp_path):
    """PID lookup は (category, product_id) 複合で判定. cross-category 汚染しない."""
    req = tmp_path / "requests"
    req.mkdir()
    # pokemon 依頼書に one_piece の PID が偶然一致してもヒットさせない
    (req / "2026-08-03_auto_catalog_add_pokemon_tcg.md").write_text(
        "| `cert555555555 POKEMON X [Y] #1 (auto候補OP01-024_PRB01=該当なし 要調査)` "
        "| 2026-08-03 |\n", encoding="utf-8")
    db = _seed_db(tmp_path)
    rows = afm.scan_requests(req)
    conn = sqlite3.connect(str(db))
    try:
        cls = afm.classify(rows, conn)
    finally:
        conn.close()
    # pokemon カテゴリでは OP01-024_PRB01 は無い → true_miss
    assert not any(r["cert"] == "555555555" for r in cls["false_miss"])
    assert any(r["cert"] == "555555555" for r in cls["true_miss"])
