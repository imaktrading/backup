"""KEー カテゴリ prefix 案B — Phase1b 読む側後方互換 test.

依頼: iMak_data/dedupe/requests/2026-07-27_key_category_prefix_phase1_reader.md

検証契約 (= HQ dup_guard.parse_key / group_key と同一規約):
1. `:` 含む KEー → category と product_id 分離してカテゴリ込み比較
2. `:` 含まない KEー → 従来どおり product_id のみ
3. 移行期に旧形式と新形式を同一グループにしない (= 別グループ = 出品機会を守る)
4. url-key (`item:` / `shops:`) はカテゴリ扱いしない (= 従来どおり)
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from dedupe import checker, csv_check
from dedupe.key_format import group_key, parse_key

pytestmark = pytest.mark.offline


# ============================================================================
# parse_key / group_key (= 規約単体)
# ============================================================================

class TestParseKey:
    def test_new_format_splits_category(self):
        assert parse_key("gundam_tcg:ST02-010") == ("gundam_tcg", "ST02-010")
        assert parse_key("one_piece_tcg:ST02-010") == ("one_piece_tcg", "ST02-010")

    def test_old_format_no_category(self):
        assert parse_key("ST02-010") == (None, "ST02-010")
        assert parse_key("OP10-049_p1") == (None, "OP10-049_p1")

    def test_url_key_not_category(self):
        # `:` を含むが url-key はカテゴリ扱いしない
        assert parse_key("item:m12345") == (None, "item:m12345")
        assert parse_key("shops:abc-def") == (None, "shops:abc-def")

    def test_empty(self):
        assert parse_key("") == (None, "")
        assert parse_key(None) == (None, "")
        assert parse_key("   ") == (None, "")

    def test_first_colon_only(self):
        # product_id は `:` を使わないが、 万一多重 `:` でも最初で分離
        assert parse_key("gundam_tcg:ST02-010:x") == ("gundam_tcg", "ST02-010:x")

    def test_strip(self):
        assert parse_key("  gundam_tcg:ST02-010  ") == ("gundam_tcg", "ST02-010")


class TestGroupKey:
    def test_new_format_keeps_category(self):
        assert group_key("gundam_tcg:ST02-010") == "gundam_tcg:ST02-010"

    def test_old_format_identity(self):
        assert group_key("ST02-010") == "ST02-010"

    def test_url_key_identity(self):
        assert group_key("item:m12345") == "item:m12345"
        assert group_key("shops:abc-def") == "shops:abc-def"

    def test_cross_category_distinct(self):
        """OP と Gundam の同番号は別 group_key (= 誤マージしない)."""
        assert group_key("gundam_tcg:ST02-010") != group_key("one_piece_tcg:ST02-010")

    def test_old_vs_new_distinct(self):
        """移行期: 旧 `ST02-010` と 新 `gundam_tcg:ST02-010` は別グループ."""
        assert group_key("ST02-010") != group_key("gundam_tcg:ST02-010")


# ============================================================================
# CanonicalIndex (= 中間スプシ突合 path) の category-aware 化
# ============================================================================

class TestCanonicalIndexCategoryAware:
    def test_cross_category_not_matched(self):
        """既存に gundam のみ → OP の同番号 candidate は重複扱いしない."""
        index = checker.CanonicalIndex.from_iterable(["gundam_tcg:ST02-010"])
        assert "gundam_tcg:ST02-010" in index
        assert "one_piece_tcg:ST02-010" not in index  # ← 誤除外しない (= 出品機会守る)

    def test_old_and_new_not_same_group(self):
        """旧 `ST02-010` の index に 新 `gundam_tcg:ST02-010` は含まれない (逆も)."""
        old_index = checker.CanonicalIndex.from_iterable(["ST02-010"])
        assert "gundam_tcg:ST02-010" not in old_index
        new_index = checker.CanonicalIndex.from_iterable(["gundam_tcg:ST02-010"])
        assert "ST02-010" not in new_index

    def test_same_category_matched(self):
        index = checker.CanonicalIndex.from_iterable(["gundam_tcg:ST02-010"])
        assert "gundam_tcg:ST02-010" in index

    def test_url_key_unaffected(self):
        index = checker.CanonicalIndex.from_iterable(["item:m12345"])
        assert "item:m12345" in index
        assert "shops:other" not in index

    def test_old_format_backward_compat(self):
        """旧形式のみ環境は従来どおり exact 一致."""
        index = checker.CanonicalIndex.from_iterable(["OP10-049_p1", "ST02-010"])
        assert "OP10-049_p1" in index
        assert "ST02-010" in index
        assert "OP10-049" not in index  # Sabo 分離維持


# ============================================================================
# check_csv_canonical (= 既定 --check-csv path) の category-aware 化
# ============================================================================

def _write_csv(path, rows):
    import csv
    fieldnames = list(rows[0].keys()) if rows else ["*Title"]
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_NONNUMERIC)
        w.writeheader()
        w.writerows(rows)


class TestCheckCsvCategoryAware:
    def _run(self, tmp_path, existing_keys, candidate_resolves):
        path = tmp_path / "cand.csv"
        _write_csv(path, [{"*Title": f"c{i}"} for i in range(len(candidate_resolves))])
        with patch("dedupe.resolver_io.resolve_csv_row", side_effect=candidate_resolves):
            return csv_check.check_csv_canonical(
                csv_path=path,
                existing_canonical_keys=frozenset(existing_keys),
                dry_run=True,
            )

    def test_cross_category_kept(self, tmp_path):
        """既存 gundam_tcg:ST02-010、 candidate one_piece_tcg:ST02-010 → keep (別カード)."""
        r = self._run(tmp_path, ["gundam_tcg:ST02-010"], ["one_piece_tcg:ST02-010"])
        assert r["removed"] == 0
        assert r["kept"] == 1

    def test_same_category_removed(self, tmp_path):
        """既存 gundam_tcg:ST02-010、 candidate 同一 → removed (真の重複)."""
        r = self._run(tmp_path, ["gundam_tcg:ST02-010"], ["gundam_tcg:ST02-010"])
        assert r["removed"] == 1
        assert "gundam_tcg:ST02-010" in r["removed_canonical_keys"]

    def test_old_vs_new_kept(self, tmp_path):
        """移行期: 既存 旧 `ST02-010`、 candidate 新 `gundam_tcg:ST02-010` → keep (別グループ)."""
        r = self._run(tmp_path, ["ST02-010"], ["gundam_tcg:ST02-010"])
        assert r["removed"] == 0
        assert r["kept"] == 1

    def test_old_format_backward_compat_removed(self, tmp_path):
        """旧形式のみ: 既存 `OP10-049_p1`、 candidate 同一 → removed (従来どおり)."""
        r = self._run(tmp_path, ["OP10-049_p1"], ["OP10-049_p1"])
        assert r["removed"] == 1

    def test_url_key_backward_compat(self, tmp_path):
        """url-key は従来どおり exact 一致で removed."""
        r = self._run(tmp_path, ["item:m12345"], ["item:m12345"])
        assert r["removed"] == 1
