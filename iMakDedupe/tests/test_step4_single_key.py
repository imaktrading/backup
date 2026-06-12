"""Step 4 (= 2026-06-10) single canonical KEY 化 test.

spec: iMak_data/KEY_REDESIGN_SPEC.md
greenlight: iMak_data/dedupe/requests/2026-06-10_key_redesign_BUILD_step4_single_key.md

検証対象:
1. Sabo OP10-049_p1 vs bare OP10-049 が **別 KEY** で誤マージしない (= 依頼書 §5 必須 test)
2. 表示と実体 SSOT 化 (= csv_check_canonical で result["removed"] と物理 kept_rows 件数一致)
3. resolver fail-closed (= 解決不能 "" は突合対象外)
4. 単一 canonical KEY 突合 (= tuple 廃止後の純粋同一性判定)
"""

from __future__ import annotations

import csv
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from dedupe import checker, csv_check

pytestmark = pytest.mark.offline


# ============================================================================
# Sabo 別 KEY 判定 (= 誤マージ防止、 依頼書 §5 必須 test)
# ============================================================================

class TestSaboBareKeyIsolation:
    def test_sabo_promo_p1_is_not_same_key_as_bare(self):
        """OP10-049_p1 (= Sabo promo) と bare OP10-049 (= 通常版) が別 KEY と認識.

        単一 KEY 突合では tuple ("OP10-049", "pro") vs ("OP10-049", "") の旧 logic と異なり、
        product_id 文字列が **そのまま suffix 込みで保持** されるため別物として扱われる。
        """
        index = checker.CanonicalIndex.from_iterable(["OP10-049"])
        # Sabo promo が誤って bare と同じ扱いされない (= 別 KEY なので index に含まれない)
        assert "OP10-049_p1" not in index
        assert "OP10-049" in index

    def test_bare_op10_049_does_not_match_p1(self):
        """逆方向: bare KEY1='OP10-049' の row は OP10-049_p1 index に含まれない."""
        index = checker.CanonicalIndex.from_iterable(["OP10-049_p1"])
        assert "OP10-049" not in index
        assert "OP10-049_p1" in index

    def test_multiple_promo_variants_distinct(self):
        """同 bare の複数 promo (= _p1 / _p2 / _P / _P_BS4) を全て別 KEY と認識."""
        variants = ["OP10-049", "OP10-049_p1", "OP10-049_p2", "OP10-049_P", "OP10-049_P_BS4"]
        index = checker.CanonicalIndex.from_iterable(variants)
        assert len(index) == 5
        for v in variants:
            assert v in index

    def test_canonical_index_empty_string_skipped(self):
        """fail-closed: 空文字列は index 投入対象外."""
        index = checker.CanonicalIndex.from_iterable(["OP10-049_p1", "", "  ", "OP10-049"])
        assert len(index) == 2
        assert "" not in index


# ============================================================================
# classify_canonical_key (= 単一 KEY 型分類)
# ============================================================================

class TestClassifyCanonicalKey:
    def test_product_id_classified(self):
        assert checker.classify_canonical_key("OP10-049_p1") == checker.KEY_TYPE_PRODUCT_ID
        assert checker.classify_canonical_key("DW-5600-1JF") == checker.KEY_TYPE_PRODUCT_ID

    def test_url_key_classified(self):
        assert checker.classify_canonical_key("item:m12345") == checker.KEY_TYPE_URL_KEY
        assert checker.classify_canonical_key("shops:abc-def") == checker.KEY_TYPE_URL_KEY

    def test_empty_failed(self):
        assert checker.classify_canonical_key("") == checker.KEY_TYPE_FAILED
        assert checker.classify_canonical_key("   ") == checker.KEY_TYPE_FAILED
        assert checker.classify_canonical_key(None) == checker.KEY_TYPE_FAILED


# ============================================================================
# classify_row_canonical (= 単一 KEY 突合 fail-closed)
# ============================================================================

class TestClassifyRowCanonical:
    def test_duplicate_detected(self):
        """既存 index に同 canonical KEY あれば FLAG_DUP_CANONICAL."""
        index = checker.CanonicalIndex.from_iterable(["OP10-049_p1"])
        with patch(
            "dedupe.resolver_io.resolve_sheet_row",
            return_value="OP10-049_p1",
        ):
            flag, key = checker.classify_row_canonical(
                title="Sabo", url="", existing=index
            )
        assert flag == checker.FLAG_DUP_CANONICAL
        assert key == "OP10-049_p1"

    def test_new_when_not_in_index(self):
        index = checker.CanonicalIndex.from_iterable(["OP10-049"])
        with patch(
            "dedupe.resolver_io.resolve_sheet_row",
            return_value="OP10-049_p1",
        ):
            flag, key = checker.classify_row_canonical(
                title="Sabo promo", url="", existing=index
            )
        assert flag == checker.FLAG_NEW
        assert key == "OP10-049_p1"

    def test_unknown_when_resolution_fails(self):
        """fail-closed: resolver "" 返却なら FLAG_UNKNOWN (= keep over remove)."""
        index = checker.CanonicalIndex.from_iterable(["OP10-049_p1"])
        with patch("dedupe.resolver_io.resolve_sheet_row", return_value=""):
            flag, key = checker.classify_row_canonical(
                title="不明な title", url="", existing=index
            )
        assert flag == checker.FLAG_UNKNOWN
        assert key == ""


# ============================================================================
# csv_check.check_csv_canonical 表示/実体 SSOT (= 依頼書 §5 / Q5 仮説対応)
# ============================================================================

def _write_csv(path: Path, rows: list) -> None:
    fieldnames = list(rows[0].keys()) if rows else ["*Title"]
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_NONNUMERIC)
        w.writeheader()
        w.writerows(rows)


class TestCsvCheckCanonicalSSOT:
    def test_total_equals_removed_plus_kept(self, tmp_path):
        """invariant: total == removed + kept (= csv_check_canonical 内 assert)."""
        path = tmp_path / "in.csv"
        _write_csv(
            path,
            [
                {"*Title": "row1", "C:Card Number": "001"},
                {"*Title": "row2", "C:Card Number": "002"},
                {"*Title": "row3", "C:Card Number": "003"},
            ],
        )
        # resolver mock: row1=既存 KEY、 row2=新規、 row3=解決不能
        with patch(
            "dedupe.resolver_io.resolve_csv_row",
            side_effect=["EXISTING-KEY", "NEW-KEY", ""],
        ):
            result = csv_check.check_csv_canonical(
                csv_path=path,
                existing_canonical_keys=frozenset({"EXISTING-KEY"}),
                dry_run=True,
                strict_mode=True,
            )
        # SSOT invariant assertion (= 関数内 assert で保証、 ここでも明示確認)
        assert result["total"] == result["removed"] + result["kept"]
        assert result["total"] == 3
        # row1 = 既存重複 + row3 = strict_mode で解決不能除外 = removed=2、 row2 = kept=1
        assert result["removed"] == 2
        assert result["kept"] == 1
        assert result["unknown"] == 1
        assert result["skipped_unresolved"] == 1

    def test_physical_kept_count_matches_displayed_kept(self, tmp_path):
        """物理書出された row 数が表示 result["kept"] と一致 (= 表示/実体 SSOT、 §5 仮説対応)."""
        path = tmp_path / "in.csv"
        _write_csv(
            path,
            [
                {"*Title": "row1", "C:Card Number": "001"},
                {"*Title": "row2", "C:Card Number": "002"},
                {"*Title": "row3", "C:Card Number": "003"},
            ],
        )
        with patch(
            "dedupe.resolver_io.resolve_csv_row",
            side_effect=["EXISTING-KEY", "NEW-KEY", "ANOTHER-NEW"],
        ):
            result = csv_check.check_csv_canonical(
                csv_path=path,
                existing_canonical_keys=frozenset({"EXISTING-KEY"}),
                dry_run=False,
                strict_mode=False,
            )
        # 物理 file を読み直して row 数 = kept と一致 verify
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            physical_rows = list(reader)
        assert len(physical_rows) == result["kept"]
        assert len(physical_rows) == 2

    def test_strict_mode_false_keeps_unresolved(self, tmp_path):
        """strict_mode=False: 解決不能 row は keep (= 旧 dedupe 互換)."""
        path = tmp_path / "in.csv"
        _write_csv(
            path,
            [
                {"*Title": "row1", "C:Card Number": "001"},
                {"*Title": "row2_unresolved", "C:Card Number": ""},
            ],
        )
        with patch(
            "dedupe.resolver_io.resolve_csv_row", side_effect=["NEW-KEY", ""]
        ):
            result = csv_check.check_csv_canonical(
                csv_path=path,
                existing_canonical_keys=frozenset(),
                dry_run=True,
                strict_mode=False,
            )
        assert result["removed"] == 0  # strict_mode=False → 解決不能でも除外しない
        assert result["kept"] == 2
        assert result["unknown"] == 1
        assert result["skipped_unresolved"] == 0


# ============================================================================
# Sabo 完全シナリオ統合 (= 依頼書背景 §「Sabo cert 146614864」 再現)
# ============================================================================

class TestSaboScenarioIntegration:
    def test_sabo_csv_not_duplicated_by_bare_existing(self, tmp_path):
        """既存スプシ KEY1='OP10-049' (= bare) があっても、
        新規 CSV の Sabo (= resolver で OP10-049_p1 解決) は **誤マージ防止** ✅.

        依頼書背景の症状 (= Sabo CSV が消える bug) の単一 KEY 化での再発防止 verify.
        """
        path = tmp_path / "sabo.csv"
        _write_csv(
            path,
            [
                {"*Title": "Sabo PSA10 Premium Collection", "C:Card Number": "049"},
            ],
        )
        # resolver mock: Sabo = OP10-049_p1
        with patch(
            "dedupe.resolver_io.resolve_csv_row", return_value="OP10-049_p1"
        ):
            result = csv_check.check_csv_canonical(
                csv_path=path,
                # 既存スプシには bare OP10-049 のみ (= 通常版が別 row で出品済)
                existing_canonical_keys=frozenset({"OP10-049"}),
                dry_run=True,
                strict_mode=True,
            )
        # Sabo (= OP10-049_p1) は bare (= OP10-049) と別 KEY なので削除されない (= 誤マージ防止)
        assert result["removed"] == 0
        assert result["kept"] == 1
        assert result["unknown"] == 0
