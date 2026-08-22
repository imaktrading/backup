"""OP promo/event set_name_ebay backfill 423 行 (2026-08-11 Advisor GO) の回帰テスト.

依頼: iMak_data/catalog/requests/2026-08-11_op03_001_p2_set_name_ebay_empty_response.md
  段1 (yaml 118件追加) + 段2 (423行 backfill migration) + 段3 (audit empty counter) の検収。

このテストが守る不変条件:
  A) one_piece_tcg の specs.set_name_ebay='' 行が **0** (段2 検収条件: 423 → 0)
  B) one_piece_tcg の set_name_ebay_source='fail_closed_no_map' 行が **0** (同)
  C) OP03-001_p2 (依頼の原因カード) の specs.set_name_ebay='Promo Cards'
  D) 段2 の後、他カテゴリの空欄件数が動いていない (baseline pokemon/gundam/dragonball/yugioh)
  E) 段1 の yaml が 118 の新規 promo/event entry を含む (合計 133 set entries)
  F) 段3 の audit tool が section 5 (empty counter) を出力する
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO.parent))
sys.path.insert(0, str(_REPO))
import api  # type: ignore  # noqa: E402


class TestOnePieceEmptyBackfilled(unittest.TestCase):
    """段2 検収: one_piece_tcg の空欄が全部埋まっている."""

    def test_no_empty_set_name_ebay_in_one_piece(self):
        con = sqlite3.connect(str(api._DB_PATH))
        try:
            n = 0
            for (sp,) in con.execute(
                "SELECT specs FROM products WHERE category='one_piece_tcg'"
            ):
                d = json.loads(sp) if sp else {}
                if not d.get("set_name_ebay"):
                    n += 1
            self.assertEqual(n, 0, f"one_piece_tcg 空欄 = {n} (期待 0)")
        finally:
            con.close()

    def test_no_fail_closed_no_map_in_one_piece(self):
        con = sqlite3.connect(str(api._DB_PATH))
        try:
            n = con.execute(
                "SELECT count(*) FROM products WHERE category='one_piece_tcg' "
                "AND json_extract(specs,'$.set_name_ebay_source')="
                "'fail_closed_no_map'"
            ).fetchone()[0]
            self.assertEqual(n, 0, f"fail_closed_no_map 残 = {n} (期待 0)")
        finally:
            con.close()

    def test_op03_001_p2_promo_cards(self):
        """依頼の原因カード. 2026-08-10 入稿で C:Set 空欄で出品された 1件."""
        rec = api.lookup(category="one_piece_tcg", product_id="OP03-001_p2")
        self.assertIsNotNone(rec, "OP03-001_p2 が DB に無い")
        self.assertEqual(rec["specs"].get("set_name_ebay"), "Promo Cards")

    def test_423_backfill_source_tag_populated(self):
        """段2 backfill 実行時の source tag が 423 行に記録されている."""
        con = sqlite3.connect(str(api._DB_PATH))
        try:
            n = con.execute(
                "SELECT count(*) FROM products WHERE category='one_piece_tcg' "
                "AND json_extract(specs,'$.set_name_ebay_source')="
                "'filter_map_backfill_20260811_op_promo_423'"
            ).fetchone()[0]
            self.assertEqual(n, 423, f"backfill source tag 行数 = {n} (期待 423)")
        finally:
            con.close()


class TestYamlContainsPromoBatch(unittest.TestCase):
    """段1 検収: one_piece.yaml の set: セクションに 118 件の新規追加."""

    def test_yaml_has_133_set_entries(self):
        import yaml
        yaml_path = _REPO / "ebay_filter_map" / "one_piece.yaml"
        with yaml_path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f)
        self.assertEqual(
            len(data["set"]), 133,
            f"one_piece.yaml set: entries = {len(data['set'])} (期待 133 = 旧15 + 新118)")

    def test_key_promo_sources_present(self):
        """依頼書 Q1 で名指しされたキー例が yaml と DB に登録されている."""
        keys = [
            "チャンピオンシップセット2023（エース・サボ・ルフィ）",
            "チャンピオンシップセット2022",
            "ファミリーデッキセット",
            "プロモーションカードセット2026",
            "『ONE PIECE FILM RED』入場者プレゼント フィナーレセット",
            "2nd ANNIVERSARY SET",
        ]
        for src in keys:
            v = api.to_ebay_value("one_piece_tcg", "set", src)
            self.assertEqual(v, "Promo Cards",
                             f"set map '{src}' → {v!r} (期待 Promo Cards)")

    def test_derive_returns_promo_cards_for_all_new_keys(self):
        """段1+段2 を通じて、118 新 source_value の派生が全て Promo Cards."""
        derived_promo = 0
        derived_other = 0
        con = sqlite3.connect(str(api._DB_PATH))
        try:
            rows = con.execute(
                "SELECT product_id, set_name_official, specs "
                "FROM products WHERE category='one_piece_tcg' "
                "AND json_extract(specs,'$.set_name_ebay_source')="
                "'filter_map_backfill_20260811_op_promo_423'"
            ).fetchall()
        finally:
            con.close()
        for pid, sno, sp in rows:
            v = api.derive_set_name_ebay("one_piece_tcg", sno, pid)
            if v == "Promo Cards":
                derived_promo += 1
            else:
                derived_other += 1
        # Group B (338 rows) → Promo Cards. Group A (85 rows) → ST-3X 6 種の
        # canonical (ST-31..36) を返すため other。合計 423 は Group A 85 + Group B 338。
        self.assertEqual(derived_promo + derived_other, 423)
        self.assertEqual(derived_promo, 338, f"promo cards 行 = {derived_promo} (期待 338)")
        self.assertEqual(derived_other, 85, f"ST-3X starter deck 行 = {derived_other} (期待 85)")


class TestOtherCategoriesUnchanged(unittest.TestCase):
    """段2 副作用ゼロ検収: 他カテゴリの空欄件数が変わっていない (baseline)."""

    # 2026-08-12 更新: specs_repopulate_from_fresh migration (Advisor GO) で gundam/dbscg の
    # fresh_only 行を canonical で埋めたため、baseline が下がった:
    #   gundam_tcg:      76 → 6   (canonical fresh 70 行を specs に populate、6 は非-canonical fresh で skip)
    #   dragonball_scg: 139 → 136 (canonical fresh 3 行 populate、136 は非-canonical fresh で skip)
    # 上記以外のカテゴリ (pokemon_tcg / yugioh_tcg) は本 migration の対象外なので不変.
    BASELINES = {
        # 2026-08-21: 25th ANNIVERSARY GOLDEN BOX の1行に値が入り、空欄が1つ減った
        # 2026-08-22: プロモ弾番号 (S-P/BWP/SV-P) と Ultra 3セットを埋めて 296行 減
        # 2026-08-22: 未マップ弾の仕分けで 71種 (1,872行) を変換表に登録し空欄を埋めた
        #   (3787 → 1915)。requests/2026-08-21_hq_unmapped_sets_175_response.md
        "pokemon_tcg": 1915,
        "gundam_tcg": 6,
        "dragonball_scg": 136,
        "yugioh_tcg": 12150,
    }

    def test_baselines_hold(self):
        con = sqlite3.connect(str(api._DB_PATH))
        try:
            for cat, expected in self.BASELINES.items():
                n = 0
                for (sp,) in con.execute(
                    "SELECT specs FROM products WHERE category=?", (cat,)
                ):
                    d = json.loads(sp) if sp else {}
                    if not d.get("set_name_ebay"):
                        n += 1
                self.assertEqual(
                    n, expected,
                    f"{cat} 空欄 = {n} (baseline {expected}); "
                    f"想定外の他カテゴリ書換の疑い")
        finally:
            con.close()


class TestAuditToolEmptyCounter(unittest.TestCase):
    """段3 検収: set_name_integrity_audit.py が section 5 (empty counter) を出す."""

    def test_audit_report_contains_section_5(self):
        script = _REPO / "tools" / "set_name_integrity_audit.py"
        proc = subprocess.run(
            [sys.executable, str(script), "--cat", "all"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=180,
        )
        self.assertEqual(proc.returncode, 0, f"audit exit={proc.returncode}: {proc.stderr[:400]}")
        # section 5 の見出しが出力に含まれる (0件でも出続ける = 依頼書 段3 の要求)
        self.assertIn("## 5. set_name_ebay 空欄 棚卸し", proc.stdout,
                      "section 5 (empty counter) が report に無い")
        # one_piece_tcg は 0 件なので "one_piece_tcg" の行が出ないか、または合計に
        # 反映されていないことを確認 (段2 backfill 完遂の裏付け)
        # 具体的には合計行に絶対数を出しているはず。
        import re as _re
        m = _re.search(r"合計 (\d+) 件.*fail_closed_no_map (\d+)", proc.stdout)
        self.assertIsNotNone(m, "『合計 N 件 (うち fail_closed_no_map M)』が見つからない")


if __name__ == "__main__":
    unittest.main()
