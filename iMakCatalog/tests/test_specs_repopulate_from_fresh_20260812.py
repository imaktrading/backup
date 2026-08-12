"""specs.set_name_ebay 再 populate (2026-08-12 Advisor GO) の回帰テスト.

依頼: iMak_data/catalog/requests/2026-08-11_pdca_catalog_queue_tcg_response_question_response.md
  §決定 案A commit 1: OPCG/DBSCG/Gundam の全行に _row_to_dict() の fresh 値を
  specs.set_name_ebay に上書き (canonical fresh のみ)。skip 対象は温存。

このテストが守る不変条件:
  A) OPCG/DBSCG/Gundam の canonical row では specs.set_name_ebay == _row_to_dict().set_name
     (両方 non-empty かつ fresh に CJK/bracket が無い場合)。
  B) E01-* 24 行の specs.set_name_ebay は 'Energy Marker Pack 01' のまま維持
     (fresh 側が Katakana 長形 = raw fallback のため skip し、既存の英語 canonical を温存)。
  C) 続く adapter 反転 (commit 2) が safe: 反転 adapter output を模擬計算して、
     both_populated かつ fresh != stale の canonical 行が **0 件** であること。
  D) 代表 sample の期待値: OP06-022 (Wings of the Captain) / ST16-005 (GREEN Uta) 等。
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO.parent))
sys.path.insert(0, str(_REPO))
import api  # type: ignore  # noqa: E402

_NON_CANONICAL_RE = re.compile(
    r"[぀-ゟ゠-ヿ一-鿿㐀-䶿\[\]【】]"
)


def _is_non_canonical_fresh(s: str) -> bool:
    return bool(s and _NON_CANONICAL_RE.search(s))


class TestSpecsRepopulateInvariant(unittest.TestCase):
    """A: OPCG/Gundam/DBSCG で canonical fresh row は specs == fresh."""

    CATS = ("one_piece_tcg", "gundam_tcg", "dragonball_scg")

    def test_canonical_rows_specs_equals_fresh(self):
        con = sqlite3.connect(str(api._DB_PATH))
        con.row_factory = sqlite3.Row
        try:
            mismatch = []
            for cat in self.CATS:
                for r in con.execute(
                    "SELECT * FROM products WHERE category=?", (cat,)
                ):
                    rec = api._row_to_dict(r)
                    fresh = rec.get("set_name") or ""
                    specs = json.loads(r["specs"]) if r["specs"] else {}
                    stale = specs.get("set_name_ebay") or ""
                    # 対象は canonical fresh (raw 長形 fallback は skip)
                    if not fresh:
                        continue
                    if _is_non_canonical_fresh(fresh):
                        continue
                    if not stale:
                        # canonical fresh + specs 空 は fresh_only 更新後 埋まっている筈
                        mismatch.append((cat, r["product_id"],
                                         "specs 空欄 (fresh=%r)" % fresh))
                        continue
                    if fresh != stale:
                        mismatch.append(
                            (cat, r["product_id"],
                             "specs=%r != fresh=%r" % (stale, fresh)))
        finally:
            con.close()
        self.assertEqual(
            mismatch, [],
            "canonical fresh row で specs != fresh が残っている:\n"
            + "\n".join(f"  {m}" for m in mismatch[:20])
            + (f"\n  ... (+{len(mismatch)-20} more)" if len(mismatch) > 20 else ""))


class TestE01EnergyMarkerPreserved(unittest.TestCase):
    """B: E01-* 24 行 (Energy Marker Pack 01) は英語 canonical のまま維持."""

    def test_e01_specs_remains_english_canonical(self):
        con = sqlite3.connect(str(api._DB_PATH))
        try:
            rows = con.execute(
                "SELECT product_id, json_extract(specs,'$.set_name_ebay') se "
                "FROM products WHERE category='dragonball_scg' "
                "AND product_id LIKE 'E01-%'"
            ).fetchall()
        finally:
            con.close()
        self.assertGreater(len(rows), 0, "E01-* 行が 0 件 (前提崩れ)")
        for pid, se in rows:
            self.assertEqual(
                se, "Energy Marker Pack 01",
                f"{pid}: specs.set_name_ebay={se!r} 期待 'Energy Marker Pack 01' "
                f"(fresh 側の Katakana 長形で上書きされていない筈)")


class TestReversalSafeForCanonicalRows(unittest.TestCase):
    """C: adapter 反転後、canonical row は adapter output が変わらない.

    反転前 (record.set_name or specs.set_name_ebay) と
    反転後 (specs.set_name_ebay or record.set_name) の diff がゼロ.
    """

    CATS = ("one_piece_tcg", "gundam_tcg", "dragonball_scg")

    def test_no_canonical_row_changes_under_reversal(self):
        con = sqlite3.connect(str(api._DB_PATH))
        con.row_factory = sqlite3.Row
        try:
            changing = []
            for cat in self.CATS:
                for r in con.execute(
                    "SELECT * FROM products WHERE category=?", (cat,)
                ):
                    rec = api._row_to_dict(r)
                    fresh = rec.get("set_name") or ""
                    specs = json.loads(r["specs"]) if r["specs"] else {}
                    stale = specs.get("set_name_ebay") or ""
                    before = fresh or stale or ""
                    after = stale or fresh or ""
                    if before == after:
                        continue
                    # skip 対象 (raw 長形 fresh) は既知の bug-fix 変化として除外.
                    if _is_non_canonical_fresh(fresh):
                        continue
                    changing.append(
                        (cat, r["product_id"], before, after))
        finally:
            con.close()
        self.assertEqual(
            changing, [],
            "canonical row で反転 diff が残っている:\n"
            + "\n".join(f"  {m}" for m in changing[:20]))


class TestRepresentativeSamples(unittest.TestCase):
    """D: 代表 sample の期待値."""

    def _fresh(self, cat, pid):
        r = api.lookup(category=cat, product_id=pid)
        return r["specs"].get("set_name_ebay") if r else None

    def test_op06_022_wings_of_the_captain(self):
        self.assertEqual(self._fresh("one_piece_tcg", "OP06-022"),
                         "Wings of the Captain")

    def test_st16_005_green_uta(self):
        """ST-16 (2026-08-02 GREEN prefix 追加) 反映."""
        self.assertEqual(self._fresh("one_piece_tcg", "ST16-005"), "GREEN Uta")

    def test_prb02_005_premium_booster_vol2(self):
        self.assertEqual(self._fresh("one_piece_tcg", "PRB02-005"),
                         "Premium Booster Vol.2")

    def test_gundam_gd01_100_gd03_sp_steel_requiem(self):
        """Gundam yaml 修正 'Universal Strife' -> 'Steel Requiem' の反映."""
        v = self._fresh("gundam_tcg", "GD01-100_GD03_SP")
        # GD01-100_GD03_SP の specs.set_name_ebay が Steel Requiem に更新されている.
        # (存在しなければ product_id 命名の変化を疑う)
        self.assertEqual(v, "Steel Requiem", f"got {v!r}")

    def test_dbscg_sb02_001_p1_manga_booster(self):
        """DBSCG 'Critical Blow' -> 'Manga Booster 02' 反映."""
        v = self._fresh("dragonball_scg", "SB02-001_p1")
        self.assertEqual(v, "Manga Booster 02", f"got {v!r}")


class TestSourceTagStamped(unittest.TestCase):
    """更新行に source tag が焼かれている (audit 用)."""

    SRC = "specs_repopulate_from_fresh_20260812_reversal_prep"

    def test_at_least_some_rows_have_new_source_tag(self):
        con = sqlite3.connect(str(api._DB_PATH))
        try:
            n = con.execute(
                "SELECT count(*) FROM products WHERE category IN "
                "('one_piece_tcg','gundam_tcg','dragonball_scg') "
                "AND json_extract(specs,'$.set_name_ebay_source')=?",
                (self.SRC,)).fetchone()[0]
        finally:
            con.close()
        # 実測 1065; 将来 canonical 化再走で減っても 100 未満は前提崩れ.
        self.assertGreaterEqual(
            n, 100,
            f"source={self.SRC!r} の行が {n} 件. 100 以上を期待")


if __name__ == "__main__":
    unittest.main()
