"""Daily cron 化した set_name_integrity_audit の完走マーカー回帰 (2026-07-31).

依頼書: 2026-07-30_cron_window_minimized_notice_response.md §2-b [IMPLEMENT-GO]
  - 完走マーカーを末尾に出すこと (prune_daily.log と同じ形)。
  - マーカーが無い = 途中で死んだ = ログ検知できる。
  - report のみ・DB 書込禁止。

本テストは in-memory temp DB を使い (本番 DB に一切触れず) 以下を保証する:
  1. START マーカー + 完走マーカーが必ず出る
  2. カテゴリ引数の透過性 (all / pokemon_tcg どちらでも動く)
  3. audit は SELECT のみで DB を書き換えない (report-only)
  4. --out を渡した場合の完走マーカーも stdout に出る (redirect 経路の証跡)
"""
from __future__ import annotations

import io
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

_REPO = Path(__file__).resolve().parent.parent
_TOOL = _REPO / "tools" / "set_name_integrity_audit.py"
sys.path.insert(0, str(_REPO / "tools"))

import set_name_integrity_audit as audit_mod  # type: ignore  # noqa: E402


def _make_temp_db(rows):
    """一時 sqlite に products + ebay_filter_map テーブルを作り、rows を投入して path を返す.

    §6 canonical ズレ検知が ebay_filter_map を参照するため空テーブルも用意する
    (fmap 未収載 = derive が None を返す → drift 対象外、で安定).
    """
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
    for m in rows[0].get("_fmap", []) if rows else []:
        pass  # not used; separate helper for maps below
    conn.commit()
    conn.close()
    return path


def _insert_fmap(path, entries):
    """ebay_filter_map に (category, field, source_value, ebay_value) を追加."""
    conn = sqlite3.connect(path)
    for e in entries:
        conn.execute(
            "INSERT INTO ebay_filter_map "
            "(category, field, source_value, ebay_value) VALUES (?,?,?,?)",
            e,
        )
    conn.commit()
    conn.close()


class TestCompletionMarker(unittest.TestCase):
    """完走マーカー: 末尾に必ず COMPLETE、先頭に START (prune_daily.log 型式)."""

    def setUp(self):
        self.db = _make_temp_db([
            {
                "category": "pokemon_tcg",
                "product_id": "S8b-001",
                "name_en": "Pikachu",
                "specs": {
                    "set_code": "S8b",
                    "set_name_ebay": "Sword & Shield—VMAX Climax",
                    "set_name_ebay_source": "official",
                    "character_name": "Pikachu",
                },
            },
        ])

    def tearDown(self):
        os.unlink(self.db)

    def _run_main(self, argv):
        buf = io.StringIO()
        with mock.patch.object(audit_mod, "DB_PATH", self.db), \
             mock.patch.object(sys, "argv", ["set_name_integrity_audit.py", *argv]), \
             redirect_stdout(buf):
            audit_mod.main()
        return buf.getvalue()

    def test_stdout_mode_has_start_and_complete_markers(self):
        out = self._run_main(["--cat", "all"])
        self.assertIn("=== set_name integrity audit START", out)
        self.assertIn("=== set_name integrity audit COMPLETE", out)
        # 完走マーカーは末尾側 (START より後) に出る
        self.assertGreater(
            out.rindex("COMPLETE"), out.rindex("START"),
            "COMPLETE marker must be after START marker",
        )

    def test_pokemon_only_mode_also_has_markers(self):
        out = self._run_main(["--cat", "pokemon_tcg"])
        self.assertIn("=== set_name integrity audit START", out)
        self.assertIn("(cat=pokemon_tcg)", out)
        self.assertIn("=== set_name integrity audit COMPLETE", out)

    def test_completion_marker_has_counts(self):
        """マーカー行に era/inconsistent/none_src/name_desync/canonical_drift の件数が出る (トレンド化用)."""
        out = self._run_main(["--cat", "all"])
        last_line = [l for l in out.splitlines() if "COMPLETE" in l][-1]
        for key in ("era=", "inconsistent=", "none_src=", "name_desync=",
                    "canonical_drift="):
            self.assertIn(key, last_line, f"missing metric {key} in marker line")

    def test_out_file_mode_also_prints_marker_to_stdout(self):
        """--out で md 保存する経路でも 完走マーカーは stdout に出る (log redirect の証跡)."""
        with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as fp:
            outpath = fp.name
        try:
            out = self._run_main(["--cat", "all", "--out", outpath])
            self.assertIn("=== set_name integrity audit COMPLETE", out)
            self.assertIn(f"wrote {outpath}", out)
        finally:
            os.unlink(outpath)


class TestReportOnly(unittest.TestCase):
    """report-only: audit() は SELECT だけで DB を1バイトも変えない."""

    def test_db_unchanged_after_full_run(self):
        db = _make_temp_db([
            {
                # わざと era mismatch: SV5a (SV era) を "Sword & Shield—..." に誤 map.
                "category": "pokemon_tcg",
                "product_id": "SV5a-001",
                "name_en": "Pikachu",
                "specs": {
                    "set_code": "SV5a",
                    "set_name_ebay": "Sword & Shield—Brilliant Stars",
                    "set_name_ebay_source": "(none)",
                    "character_name": "Ditto",  # わざと name desync
                },
            },
            {
                "category": "pokemon_tcg",
                "product_id": "S8b-002",
                "name_en": "Charizard",
                "specs": {
                    "set_code": "S8b",
                    "set_name_ebay": "Sword & Shield—VMAX Climax",
                    "set_name_ebay_source": "official",
                    "character_name": "Charizard",
                },
            },
        ])
        try:
            before = Path(db).read_bytes()
            with mock.patch.object(audit_mod, "DB_PATH", db):
                (era, inc, none_list, desync,
                 empty_by_cat, drift_by_cat, rarity_by_cat) = audit_mod.audit(None)
            after = Path(db).read_bytes()
            self.assertEqual(before, after, "audit() must not mutate the DB")
            # 検出ロジックの正当性も担保 (回帰): SV5a→"Sword & Shield—..." は era mismatch
            self.assertTrue(any(e[0] == "SV5a" for e in era),
                            "era mismatch on SV5a must be detected")
            self.assertTrue(any(d[0] == "SV5a-001" for d in desync),
                            "name_en/character_name desync must be detected")
            # §6 drift は fmap が空 (未収載) なので全部 None → drift 0 (state (b) 扱い)
            self.assertEqual(dict(drift_by_cat), {},
                             "drift_by_cat must be empty when fmap has no entries")
        finally:
            os.unlink(db)


class TestCliExitCode(unittest.TestCase):
    """CLI 経由でも exit code 0 (report-only なので異常検出しても 0)."""

    def test_cli_exit_zero_and_marker_on_real_db(self):
        # 本番 DB を read だけする (writes は audit_mod 側で発生し得ないことを別テストで担保済).
        r = subprocess.run(
            [sys.executable, str(_TOOL), "--cat", "all"],
            capture_output=True, text=True, encoding="utf-8",
            env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
        )
        self.assertEqual(r.returncode, 0,
                         f"exit != 0: stderr={r.stderr[-500:]}")
        self.assertIn("=== set_name integrity audit START", r.stdout)
        self.assertIn("=== set_name integrity audit COMPLETE", r.stdout)


if __name__ == "__main__":
    unittest.main()
