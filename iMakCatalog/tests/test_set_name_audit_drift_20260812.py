"""set_name_integrity_audit §6 canonical ズレ検知 回帰 (2026-08-12).

依頼書: iMak_data/catalog/requests/
  2026-08-10_ssot_contract_master_coverage_and_leaf_check_response_question_response.md
  §item 1 [IMPLEMENT-GO]:
    specs.set_name_ebay ≠ 今その場で yaml/filter_map から計算した値
    を数える。それだけ。gate にはせず、まず可視化。
    ★ 0 になっても出し続ける (0 が続いている証跡が唯一の証拠)。

本テストは in-memory temp DB (products + ebay_filter_map) を使い、以下を保証する:
  T1. state (a) canonical のズレは §6 で 1 件と数える
  T2. state (b) 自由文字列 (filter_map 未収載) は drift 対象外
  T3. state (c) 空欄も drift 対象外
  T4. drift 0 でも §6 セクションが必ず出力される (「0 が続く証跡」規約)
  T5. 完走マーカーに canonical_drift= が出る (トレンド化用)
  T6. category 別の絶対数を分けて出す
"""
from __future__ import annotations

import io
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "tools"))

import set_name_integrity_audit as audit_mod  # type: ignore  # noqa: E402


def _make_temp_db(rows, fmap_entries):
    """products + ebay_filter_map を持つ temp sqlite を作成."""
    fd, path = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE products ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "category TEXT NOT NULL,"
        "product_id TEXT NOT NULL,"
        "name_en TEXT,"
        "set_name_official TEXT,"
        "specs TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE ebay_filter_map ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "category TEXT NOT NULL,"
        "field TEXT NOT NULL,"
        "source_value TEXT NOT NULL,"
        "ebay_value TEXT NOT NULL,"
        "UNIQUE(category, field, source_value))"
    )
    for r in rows:
        conn.execute(
            "INSERT INTO products "
            "(category, product_id, name_en, set_name_official, specs) "
            "VALUES (?,?,?,?,?)",
            (r["category"], r["product_id"], r.get("name_en"),
             r.get("set_name_official"),
             json.dumps(r.get("specs", {}))),
        )
    for e in fmap_entries:
        conn.execute(
            "INSERT INTO ebay_filter_map "
            "(category, field, source_value, ebay_value) VALUES (?,?,?,?)",
            e,
        )
    conn.commit()
    conn.close()
    return path


def _run_main(db, argv):
    buf = io.StringIO()
    with mock.patch.object(audit_mod, "DB_PATH", db), \
         mock.patch.object(sys, "argv", ["set_name_integrity_audit.py", *argv]), \
         redirect_stdout(buf):
        audit_mod.main()
    return buf.getvalue()


class TestDriftDetection(unittest.TestCase):
    """T1〜T3: state (a) drift を数え、(b)/(c) は数えない."""

    def test_t1_state_a_drift_is_counted(self):
        """canonical (a) のズレは 1 件と数える (filter_map: A→B, stored=X)."""
        db = _make_temp_db(
            rows=[{
                "category": "pokemon_tcg",
                "product_id": "S8b-001",
                "set_name_official": "VMAXクライマックス",
                "specs": {
                    "set_code": "S8b",
                    # 現行焼き付け値 = 誤 canonical (別 era の英セット名)
                    "set_name_ebay": "Sword & Shield—Brilliant Stars",
                    "set_name_ebay_source": "old",
                },
            }],
            fmap_entries=[
                # 今その場で計算する canonical: VMAXクライマックス → S8b canonical.
                ("pokemon_tcg", "set", "VMAXクライマックス", "Sword & Shield—VMAX Climax"),
            ],
        )
        try:
            with mock.patch.object(audit_mod, "DB_PATH", db):
                (_, _, _, _, _, drift_by_cat, _rarity, *_extra) = audit_mod.audit(None)
            self.assertEqual(drift_by_cat.get("pokemon_tcg"), 1,
                             "state (a) drift must be counted for pokemon_tcg")
        finally:
            os.unlink(db)

    def test_t1b_no_drift_when_stored_matches_computed(self):
        """canonical (a) で stored == computed なら drift 0."""
        db = _make_temp_db(
            rows=[{
                "category": "pokemon_tcg",
                "product_id": "S8b-001",
                "set_name_official": "VMAXクライマックス",
                "specs": {
                    "set_code": "S8b",
                    "set_name_ebay": "Sword & Shield—VMAX Climax",  # 正しい canonical
                    "set_name_ebay_source": "official",
                },
            }],
            fmap_entries=[
                ("pokemon_tcg", "set", "VMAXクライマックス", "Sword & Shield—VMAX Climax"),
            ],
        )
        try:
            with mock.patch.object(audit_mod, "DB_PATH", db):
                (_, _, _, _, _, drift_by_cat, _rarity, *_extra) = audit_mod.audit(None)
            self.assertEqual(drift_by_cat, {},
                             "no drift when stored matches computed canonical")
        finally:
            os.unlink(db)

    def test_t2_state_b_free_text_not_counted(self):
        """state (b) 自由文字列 (filter_map 未収載) は drift 対象外."""
        db = _make_temp_db(
            rows=[{
                "category": "pokemon_tcg",
                "product_id": "SVAB-001",
                "set_name_official": "何かマイナーな公式表記",
                "specs": {
                    "set_name_ebay": "Free Text Set Name",  # 自由文字列で維持
                    "set_name_ebay_source": "manual",
                },
            }],
            fmap_entries=[],  # filter_map 未収載 → derive → None
        )
        try:
            with mock.patch.object(audit_mod, "DB_PATH", db):
                (_, _, _, _, _, drift_by_cat, _rarity, *_extra) = audit_mod.audit(None)
            self.assertEqual(drift_by_cat, {},
                             "state (b) free_text (fmap-miss) must not be drift")
        finally:
            os.unlink(db)

    def test_t3_state_c_empty_not_counted(self):
        """state (c) 空欄 (filter_map 未収載 + stored 空) も drift 対象外."""
        db = _make_temp_db(
            rows=[{
                "category": "one_piece_tcg",
                "product_id": "UNKNOWN-001",
                "set_name_official": None,
                "specs": {
                    "set_name_ebay": "",
                    "set_name_ebay_source": "fail_closed_no_map",
                },
            }],
            fmap_entries=[],
        )
        try:
            with mock.patch.object(audit_mod, "DB_PATH", db):
                (_, _, _, _, _, drift_by_cat, _rarity, *_extra) = audit_mod.audit(None)
            self.assertEqual(drift_by_cat, {},
                             "state (c) empty must not be drift")
        finally:
            os.unlink(db)


class TestDriftReport(unittest.TestCase):
    """T4〜T6: §6 セクションの render + 完走マーカー."""

    def test_t4_section6_always_rendered_even_when_zero(self):
        """drift 0 でも §6 セクション見出しが必ず出る (「0 が続く証跡」規約)."""
        db = _make_temp_db(
            rows=[{
                "category": "pokemon_tcg",
                "product_id": "S8b-001",
                "set_name_official": "VMAXクライマックス",
                "specs": {
                    "set_name_ebay": "Sword & Shield—VMAX Climax",
                    "set_name_ebay_source": "official",
                },
            }],
            fmap_entries=[
                ("pokemon_tcg", "set", "VMAXクライマックス", "Sword & Shield—VMAX Climax"),
            ],
        )
        try:
            out = _run_main(db, ["--cat", "all"])
            self.assertIn("## 6. canonical ズレ検知", out,
                          "§6 header must be emitted even when drift=0")
            self.assertIn("合計 0 件", out,
                          "§6 must show 合計 0 件 (0 でも出し続ける規約)")
        finally:
            os.unlink(db)

    def test_t5_completion_marker_has_canonical_drift(self):
        """完走マーカー行に canonical_drift= が出る (トレンド化用)."""
        db = _make_temp_db(
            rows=[{
                "category": "pokemon_tcg",
                "product_id": "S8b-001",
                "set_name_official": "VMAXクライマックス",
                "specs": {
                    "set_name_ebay": "Sword & Shield—Brilliant Stars",  # drift
                    "set_name_ebay_source": "old",
                },
            }],
            fmap_entries=[
                ("pokemon_tcg", "set", "VMAXクライマックス", "Sword & Shield—VMAX Climax"),
            ],
        )
        try:
            out = _run_main(db, ["--cat", "all"])
            last = [l for l in out.splitlines() if "COMPLETE" in l][-1]
            self.assertIn("canonical_drift=1", last,
                          "COMPLETE marker must include canonical_drift= count")
        finally:
            os.unlink(db)

    def test_t6_drift_by_category_absolute_counts(self):
        """§6 は category 別の絶対数を分けて出す."""
        db = _make_temp_db(
            rows=[
                {
                    "category": "pokemon_tcg",
                    "product_id": "S8b-001",
                    "set_name_official": "VMAXクライマックス",
                    "specs": {
                        "set_name_ebay": "Sword & Shield—Brilliant Stars",
                        "set_name_ebay_source": "old",
                    },
                },
                {
                    "category": "one_piece_tcg",
                    "product_id": "OP01-001",
                    "set_name_official": "ROMANCE DAWN [OP-01]",
                    "specs": {
                        "set_name_ebay": "Stale Name",
                        "set_name_ebay_source": "old",
                    },
                },
                {
                    "category": "one_piece_tcg",
                    "product_id": "OP01-002",
                    "set_name_official": "ROMANCE DAWN [OP-01]",
                    "specs": {
                        "set_name_ebay": "Another Stale",
                        "set_name_ebay_source": "old",
                    },
                },
            ],
            fmap_entries=[
                ("pokemon_tcg", "set", "VMAXクライマックス", "Sword & Shield—VMAX Climax"),
                ("one_piece_tcg", "set", "ROMANCE DAWN [OP-01]", "Romance Dawn"),
            ],
        )
        try:
            out = _run_main(db, ["--cat", "all"])
            self.assertIn("| pokemon_tcg | 1 |", out)
            self.assertIn("| one_piece_tcg | 2 |", out)
            self.assertIn("合計 3 件", out)
        finally:
            os.unlink(db)


class TestDriveBySetCodeFallback(unittest.TestCase):
    """derive の 3 段 fallback (①set_official ②[CODE] ③pid prefix) を drift 計算に使うことの回帰."""

    def test_fallback_by_bracket_code(self):
        """set_official に filter_map 直接 hit なし → [CODE] 抽出で set_code lookup が効く."""
        db = _make_temp_db(
            rows=[{
                "category": "one_piece_tcg",
                "product_id": "OP06-022",
                "set_name_official": "BOOSTER PACK -WINGS OF THE CAPTAIN- [OP-06]",
                "specs": {
                    # stored に古い焼き付けが残っている
                    "set_name_ebay": "Wrong Old Name",
                    "set_name_ebay_source": "old",
                },
            }],
            fmap_entries=[
                # set 直接 map なし、[OP-06] → set_code map あり
                ("one_piece_tcg", "set_code", "OP-06", "Wings of the Captain"),
            ],
        )
        try:
            with mock.patch.object(audit_mod, "DB_PATH", db):
                (_, _, _, _, _, drift_by_cat, _rarity, *_extra) = audit_mod.audit(None)
            self.assertEqual(drift_by_cat.get("one_piece_tcg"), 1,
                             "drift must be caught via [CODE] fallback derive")
        finally:
            os.unlink(db)

    def test_fallback_by_pid_prefix(self):
        """set_official/[CODE] hit なし → product_id prefix で set_code lookup が効く."""
        db = _make_temp_db(
            rows=[{
                "category": "pokemon_tcg",
                "product_id": "S8b-042",
                "set_name_official": None,  # 公式表記なし
                "specs": {
                    "set_name_ebay": "Wrong Old Name",
                    "set_name_ebay_source": "old",
                },
            }],
            fmap_entries=[
                ("pokemon_tcg", "set_code", "S8b", "Sword & Shield—VMAX Climax"),
            ],
        )
        try:
            with mock.patch.object(audit_mod, "DB_PATH", db):
                (_, _, _, _, _, drift_by_cat, _rarity, *_extra) = audit_mod.audit(None)
            self.assertEqual(drift_by_cat.get("pokemon_tcg"), 1,
                             "drift must be caught via product_id prefix fallback derive")
        finally:
            os.unlink(db)


if __name__ == "__main__":
    unittest.main()
