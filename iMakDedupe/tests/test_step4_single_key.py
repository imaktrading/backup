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


def _rwc_dict(k):
    """key 文字列 → resolve_csv_row_with_category の戻り dict (Phase3 dual-mode 対応)."""
    from dedupe.key_format import parse_key
    cat, pid = parse_key(k)
    return {"product_id": pid, "category": cat or ""}


def _rwc_side(keys):
    """key 文字列 list → resolve_csv_row_with_category の side_effect 関数."""
    it = iter(keys)

    def _fn(row, purpose="dedup"):
        return _rwc_dict(next(it))

    return _fn


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
            "dedupe.resolver_io.resolve_csv_row_with_category",
            side_effect=_rwc_side(["EXISTING-KEY", "NEW-KEY", ""]),
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
            "dedupe.resolver_io.resolve_csv_row_with_category",
            side_effect=_rwc_side(["EXISTING-KEY", "NEW-KEY", "ANOTHER-NEW"]),
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
            "dedupe.resolver_io.resolve_csv_row_with_category",
            side_effect=_rwc_side(["NEW-KEY", ""]),
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
            "dedupe.resolver_io.resolve_csv_row_with_category",
            return_value=_rwc_dict("OP10-049_p1"),
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


# ============================================================================
# 2026-06-16 回帰: unresolved を物理除外しない (= failclosed_must_skip)
# 依頼書: dedupe/requests/2026-06-16_unresolved_must_not_be_removed.md
# 背景: Mercari (Porter/montbell/tshirt/reel) は catalog KEY 無し = 全 unresolved。
#       strict 除外だと全 10 件削除 → CSV 0 行 (= Porter 全除外事故)。
# ============================================================================

class TestUnresolvedNotRemoved:
    def test_all_unresolved_mercari_kept_not_removed(self, tmp_path):
        """Porter 再現: 全 row が catalog KEY 無し (unresolved) → removed=0 / kept=all."""
        path = tmp_path / "porter.csv"
        _write_csv(
            path,
            [
                {"*Title": "Porter bag A", "C:Card Number": ""},
                {"*Title": "Porter bag B", "C:Card Number": ""},
                {"*Title": "Porter bag C", "C:Card Number": ""},
            ],
        )
        # Mercari 1 点もの = catalog 突合不能 = 全 unresolved ("")
        with patch(
            "dedupe.resolver_io.resolve_csv_row_with_category",
            side_effect=_rwc_side(["", "", ""]),
        ):
            result = csv_check.check_csv_canonical(
                csv_path=path,
                existing_canonical_keys=frozenset(),
                dry_run=True,
                # 既定挙動 (strict_mode 省略 = False) で確認
            )
        assert result["removed"] == 0  # 真の重複ゼロ = 除外ゼロ
        assert result["kept"] == 3  # 全件保持 (= Porter 全除外事故の防止)
        assert result["unknown"] == 3  # unresolved は unknown 計上のみ
        assert result["skipped_unresolved"] == 0  # 除外していない

    def test_check_csv_canonical_default_is_keep_unresolved(self, tmp_path):
        """check_csv_canonical の strict_mode 省略時デフォルト = keep (= 6/16 是正)."""
        path = tmp_path / "in.csv"
        _write_csv(path, [{"*Title": "x", "C:Card Number": ""}])
        with patch("dedupe.resolver_io.resolve_csv_row_with_category",
                   side_effect=_rwc_side([""])):
            result = csv_check.check_csv_canonical(
                csv_path=path,
                existing_canonical_keys=frozenset(),
                dry_run=True,
            )
        assert result["removed"] == 0
        assert result["kept"] == 1

    def test_catalog_keyed_removes_only_true_dup_keeps_unresolved(self, tmp_path):
        """catalog-keyed 混在: 真の重複は除外 / 新規 + unresolved は保持."""
        path = tmp_path / "mix.csv"
        _write_csv(
            path,
            [
                {"*Title": "dup", "C:Card Number": "001"},       # 既存と一致 → 除外
                {"*Title": "new", "C:Card Number": "002"},       # 新規 → 保持
                {"*Title": "unresolved", "C:Card Number": ""},   # 解決不能 → 保持
            ],
        )
        with patch(
            "dedupe.resolver_io.resolve_csv_row_with_category",
            side_effect=_rwc_side(["OP01-001", "OP01-002", ""]),
        ):
            result = csv_check.check_csv_canonical(
                csv_path=path,
                existing_canonical_keys=frozenset({"OP01-001"}),
                dry_run=True,
            )
        assert result["removed"] == 1  # 真の重複のみ
        assert result["kept"] == 2  # 新規 + unresolved
        assert result["unknown"] == 1
        assert result["skipped_unresolved"] == 0

    def test_run_check_csv_canonical_forwards_strict_mode_default_false(self, tmp_path):
        """CLI 経路 run_check_csv_canonical の既定が strict_mode=False を渡すこと.

        sheet_io を mock し、 check_csv_canonical に渡る strict_mode を捕捉して検証.
        2026-08-07: load_live_itemid_set も mock (= 依頼書 §Q2 実装後の必要 mock).
        """
        path = tmp_path / "in.csv"
        _write_csv(path, [{"*Title": "x", "C:Card Number": "001"}])

        captured = {}

        def _spy(**kwargs):
            captured["strict_mode"] = kwargs.get("strict_mode")
            return {
                "total": 1, "removed": 0, "kept": 1, "unknown": 0,
                "skipped_unresolved": 0, "removed_titles": [],
                "removed_canonical_keys": [], "backup_path": "", "csv_path": str(path),
            }

        with patch("dedupe.sheet_io.load_live_itemid_set", return_value=frozenset({"999"})), \
             patch("dedupe.sheet_io.authorize_client", return_value=MagicMock()), \
             patch("dedupe.sheet_io.open_spreadsheet", return_value=MagicMock()), \
             patch("dedupe.sheet_io.find_canonical_key_column", return_value=None), \
             patch("dedupe.csv_check.check_csv_canonical", side_effect=_spy):
            # 既定 (= strict_mode 省略)
            checker.run_check_csv_canonical(csv_path=str(path), dry_run=True)
        assert captured["strict_mode"] is False  # 既定 = keep-unresolved

    def test_run_check_csv_canonical_forwards_strict_mode_true_optin(self, tmp_path):
        """CLI 経路: strict_mode=True を明示すると check_csv_canonical に True が渡る (opt-in).

        2026-08-07: load_live_itemid_set も mock (= 依頼書 §Q2 実装後の必要 mock).
        """
        path = tmp_path / "in.csv"
        _write_csv(path, [{"*Title": "x", "C:Card Number": "001"}])

        captured = {}

        def _spy(**kwargs):
            captured["strict_mode"] = kwargs.get("strict_mode")
            return {
                "total": 1, "removed": 0, "kept": 1, "unknown": 0,
                "skipped_unresolved": 0, "removed_titles": [],
                "removed_canonical_keys": [], "backup_path": "", "csv_path": str(path),
            }

        with patch("dedupe.sheet_io.load_live_itemid_set", return_value=frozenset({"999"})), \
             patch("dedupe.sheet_io.authorize_client", return_value=MagicMock()), \
             patch("dedupe.sheet_io.open_spreadsheet", return_value=MagicMock()), \
             patch("dedupe.sheet_io.find_canonical_key_column", return_value=None), \
             patch("dedupe.csv_check.check_csv_canonical", side_effect=_spy):
            checker.run_check_csv_canonical(
                csv_path=str(path), dry_run=True, strict_mode=True
            )
        assert captured["strict_mode"] is True


# ============================================================================
# 2026-07-13 BUILD → 2026-08-07 再是正: 既存判定 filter を eBay ActiveList (HQ cache) 基準に
# 依頼: dedupe/requests/2026-08-04_live_definition_must_be_ebay_not_sold_column_response.md
# 旧: itemID(B) 非空 AND sold(D) 空 = live proxy → 補URL 運用で D='○' でも eBay 側は live
#     な行が 661 件、 これが誤脱落 → 重複素通り (8/03 8/04 の 2 件が実害)。
# 新: itemID(B) が HQ live_listings_cache に含まれる行 = live の真実。
#     orphan(B空) は従来どおり除外。 D 列は live 判定から外す (analysis 用途で残す)。
# ============================================================================

def _fake_ws(values):
    ws = MagicMock()
    ws.get_all_values.return_value = values
    ws.col_values.side_effect = lambda c: [r[c - 1] if len(r) >= c else "" for r in values]
    return ws


class TestLiveFilterItemIdBuild:
    # 商品管理シート layout: A=URL, B=itemID, C=title, D=sold, E=KEY(canonical)
    _HEADER = ["URL", "itemID", "title", "売り切れ", "KEY"]

    def _run_with_low_rows(self, tmp_path, low_rows, csv_resolves, live_itemid_set):
        """LOW を fake ws にして run_check_csv_canonical を実走 (実 sheet 読込は本物)."""
        from dedupe import sheet_io
        low_ws = _fake_ws([self._HEADER] + low_rows)
        high_ws = _fake_ws([self._HEADER])  # HIGH は空 (key_col None で skip)

        def _open(sid, client=None):
            m = MagicMock()
            m.worksheet.return_value = (
                low_ws if sid == sheet_io.LOW_SHEET_ID else high_ws
            )
            return m

        def _findkey(ws):
            return 5 if ws is low_ws else None  # LOW のみ KEY 列 (E=5)

        path = tmp_path / "cand.csv"
        _write_csv(
            path,
            [{"*Title": f"cand{i}", "C:Card Number": ""} for i in range(len(csv_resolves))],
        )
        with patch("dedupe.sheet_io.load_live_itemid_set", return_value=live_itemid_set), \
             patch("dedupe.sheet_io.authorize_client", return_value=MagicMock()), \
             patch("dedupe.sheet_io.open_spreadsheet", side_effect=_open), \
             patch("dedupe.sheet_io.find_canonical_key_column", side_effect=_findkey), \
             patch("dedupe.resolver_io.resolve_csv_row_with_category", side_effect=_rwc_side(csv_resolves)), \
             patch("dedupe.csv_check.check_csv_canonical", wraps=csv_check.check_csv_canonical) as spy:
            checker.run_check_csv_canonical(csv_path=str(path), dry_run=True)
        return spy.call_args

    def test_existing_set_is_activelist_membership(self, tmp_path):
        """新方針: 既存 set = itemID が HQ cache (eBay ActiveList) に含まれる row のみ.

        D 列は無視 (= 2026-08-07 是正)。 orphan (B空) は従来どおり除外。
        """
        low_rows = [
            ["u1", "111", "t1", "", "LIVE-KEY"],       # itemID live → 既存に入る
            ["u2", "", "t2", "", "ORPHAN-KEY"],        # B空 = 未出品 → 除外
            ["u3", "999", "t3", "", "DEAD-KEY"],       # itemID 非 live → 除外
            ["u4", "333", "t4", "○", "STILL-LIVE-KEY"], # D='○' でも itemID live → 含む (★新方針)
        ]
        live_set = frozenset({"111", "333"})  # 999 は無い (= eBay で終了)
        call = self._run_with_low_rows(tmp_path, low_rows, csv_resolves=["X"], live_itemid_set=live_set)
        existing = call.kwargs["existing_canonical_keys"]
        assert "LIVE-KEY" in existing
        assert "ORPHAN-KEY" not in existing  # orphan (B空) 引き続き除外
        assert "DEAD-KEY" not in existing    # eBay で終了 → 除外
        assert "STILL-LIVE-KEY" in existing  # ★D='○' でも eBay live なら含む (本件の核)

    def test_live_candidate_removed_orphan_candidate_kept(self, tmp_path):
        """新規候補: live 一致は除外 / orphan 一致は keep (= 誤ブロック解消).

        2026-08-07: live 判定は HQ cache 由来 (live_itemid_set) に切替済。
        """
        low_rows = [
            ["u1", "111", "t1", "", "LIVE-KEY"],
            ["u2", "", "t2", "", "ORPHAN-KEY"],
        ]
        from dedupe import sheet_io
        low_ws = _fake_ws([self._HEADER] + low_rows)
        high_ws = _fake_ws([self._HEADER])

        def _open(sid, client=None):
            m = MagicMock()
            m.worksheet.return_value = low_ws if sid == sheet_io.LOW_SHEET_ID else high_ws
            return m

        def _findkey(ws):
            return 5 if ws is low_ws else None

        path = tmp_path / "cand.csv"
        _write_csv(path, [
            {"*Title": "cand_live", "C:Card Number": ""},
            {"*Title": "cand_orphan", "C:Card Number": ""},
        ])
        captured = {}
        real = csv_check.check_csv_canonical

        def _wrap(**kw):
            r = real(**kw)
            captured["result"] = r
            return r

        with patch("dedupe.sheet_io.load_live_itemid_set", return_value=frozenset({"111"})), \
             patch("dedupe.sheet_io.authorize_client", return_value=MagicMock()), \
             patch("dedupe.sheet_io.open_spreadsheet", side_effect=_open), \
             patch("dedupe.sheet_io.find_canonical_key_column", side_effect=_findkey), \
             patch("dedupe.resolver_io.resolve_csv_row_with_category", side_effect=_rwc_side(["LIVE-KEY", "ORPHAN-KEY"])), \
             patch("dedupe.csv_check.check_csv_canonical", side_effect=_wrap):
            checker.run_check_csv_canonical(csv_path=str(path), dry_run=True)
        r = captured["result"]
        assert r["removed"] == 1  # LIVE-KEY のみ除外
        assert r["kept"] == 1     # ORPHAN-KEY は keep (= 未出品なので誤ブロックしない)
        assert "LIVE-KEY" in r["removed_canonical_keys"]
        assert "ORPHAN-KEY" not in r["removed_canonical_keys"]
        # live 保証フラグ
        assert r["live_guaranteed"] is True
        assert r["removed_keys_live"] == r["removed_canonical_keys"]

    def test_listings_col_itemid_constant_is_b(self):
        """LISTINGS_COL_ITEMID = 2 (= B列) であること (= 是正の定数根拠)."""
        from dedupe import sheet_io
        assert sheet_io.LISTINGS_COL_ITEMID == 2
        assert sheet_io.LISTINGS_COL_URL == 1  # A は URL (= itemID 代用しない)
