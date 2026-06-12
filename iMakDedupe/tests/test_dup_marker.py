"""dup_marker test (= 2026-06-12 D列 "DUP" 書込 fail-closed 検証).

spec: iMak_data/dedupe/requests/2026-06-12_gshock_dup_writeback_METHOD_APPROVED_greenlight.md

検証:
1. fail-closed: 既存出品 KEY と完全一致した B空 row のみ mark
2. B非空 / D非空 row は touch しない (= 既出品 / 売切 / 既マーク)
3. 解決不能 ("") は mark しない
4. category_filter 動作 (= G-shock 以外は対象外)
5. AI 列既書込み済優先 (= scope1 では resolver 呼ばない)
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from dedupe import dup_marker

pytestmark = pytest.mark.offline


def _ws_with(values):
    ws = MagicMock()
    ws.get_all_values.return_value = values
    return ws


# row layout: A=URL, B=itemID, C=title, D=sold, ..., R=category, AI=KEY
# 簡略化: col 1=URL, 2=item_id, 3=title, 4=sold, 18=category, 35=KEY
def _row(
    url="",
    item_id="",
    title="",
    sold="",
    category="",
    key="",
):
    out = [""] * 35
    out[0] = url
    out[1] = item_id
    out[2] = title
    out[3] = sold
    out[17] = category
    out[34] = key
    return out


HEADER = _row(url="URL", item_id="itemID", title="title", sold="売り切れ", category="カテゴリ", key="KEY")


# ============================================================================
# find_b_empty_d_empty_targets
# ============================================================================

class TestFindBEmptyDEmpty:
    def test_picks_b_empty_d_empty_gshock(self):
        """B空 AND D空 AND category='G-shock' のみ抽出."""
        ws = _ws_with([
            HEADER,
            _row(url="u1", item_id="", title="t1", sold="", category="G-shock", key="DW-5600"),
            _row(url="u2", item_id="123", title="t2", sold="", category="G-shock", key="DW-5601"),  # B非空 → 除外
            _row(url="u3", item_id="", title="t3", sold="○", category="G-shock", key="DW-5602"),  # D非空 → 除外
            _row(url="u4", item_id="", title="t4", sold="", category="TCG", key="OP01-001"),  # 他カテゴリ → 除外
        ])
        targets = dup_marker.find_b_empty_d_empty_targets(ws, category_filter="G-shock")
        assert len(targets) == 1
        assert targets[0]["row_idx"] == 2  # header + 1
        assert targets[0]["key_current"] == "DW-5600"

    def test_no_category_filter(self):
        """category_filter=None なら 全カテゴリ対象."""
        ws = _ws_with([
            HEADER,
            _row(url="u1", item_id="", title="t1", sold="", category="G-shock"),
            _row(url="u2", item_id="", title="t2", sold="", category="TCG"),
        ])
        targets = dup_marker.find_b_empty_d_empty_targets(ws, category_filter=None)
        assert len(targets) == 2


# ============================================================================
# collect_existing_canonical_keys (= B非空 row の KEY 集約)
# ============================================================================

class TestCollectExistingKeys:
    def test_collects_b_non_empty_keys_from_both_sheets(self):
        """HIGH + LOW の B非空 row の KEY を統合."""
        ws_high = _ws_with([
            HEADER,
            _row(item_id="ebay1", key="OP10-049_p1"),
            _row(item_id="", key="OP10-049"),  # B空 → 除外
        ])
        ws_low = _ws_with([
            HEADER,
            _row(item_id="ebay2", key="DW-5600"),
            _row(item_id="ebay3", key="GA-2100"),
            _row(item_id="", key="DW-5601"),  # B空 → 除外
        ])
        keys = dup_marker.collect_existing_canonical_keys(ws_high, ws_low)
        assert keys == {"OP10-049_p1", "DW-5600", "GA-2100"}


# ============================================================================
# select_dup_marks (= fail-closed 完全一致のみ)
# ============================================================================

class TestSelectDupMarks:
    def test_only_exact_match_with_existing(self):
        """既存 KEY 完全一致のみ mark 対象."""
        targets = [
            {"row_idx": 2, "resolved_key": "DW-5600", "title": "t1"},
            {"row_idx": 3, "resolved_key": "DW-5601", "title": "t2"},  # 既存になし
            {"row_idx": 4, "resolved_key": "", "title": "t3"},  # 解決不能
        ]
        existing = {"DW-5600", "GA-2100"}
        marks = dup_marker.select_dup_marks(targets, existing)
        assert len(marks) == 1
        assert marks[0]["row_idx"] == 2

    def test_unresolved_excluded(self):
        """解決不能 ("") は除外 (= fail-closed)."""
        targets = [{"row_idx": 5, "resolved_key": "", "title": "x"}]
        marks = dup_marker.select_dup_marks(targets, {"DW-5600"})
        assert marks == []


# ============================================================================
# write_dup_markers (= 書込動作 dry-run)
# ============================================================================

class TestWriteDupMarkers:
    def test_dry_run_no_batch_update(self, tmp_path):
        """dry_run=True なら batch_update 呼ばれない、 marked カウントのみ."""
        ws = MagicMock()
        marks = [
            {"row_idx": 5, "resolved_key": "DW-5600", "title": "t1", "resolved_source": "ai_column"},
            {"row_idx": 7, "resolved_key": "GA-2100", "title": "t2", "resolved_source": "resolver"},
        ]
        result = dup_marker.write_dup_markers(ws, marks, dry_run=True)
        assert result["marked"] == 2
        assert result["dry_run"] is True
        ws.batch_update.assert_not_called()
        assert len(result["sample"]) == 2

    def test_real_run_calls_batch_update_with_dup_value(self, tmp_path):
        """dry_run=False → batch_update が 'DUP' 値で呼ばれる + .bak 保存."""
        ws = MagicMock()
        ws.get_all_values.return_value = [HEADER, _row(category="G-shock")]
        marks = [
            {"row_idx": 5, "resolved_key": "DW-5600", "title": "t", "resolved_source": "ai_column"},
        ]
        bak = tmp_path / "low.bak.json"
        result = dup_marker.write_dup_markers(ws, marks, dry_run=False, backup_path=bak)
        assert result["marked"] == 1
        assert result["backup_path"] == str(bak)
        assert bak.exists()
        # batch_update 引数確認
        ws.batch_update.assert_called_once()
        updates_arg = ws.batch_update.call_args[0][0]
        assert len(updates_arg) == 1
        assert updates_arg[0]["values"] == [["DUP"]]
        # D列 (= col 4) の range 含む A1 表記
        assert "D" in updates_arg[0]["range"].upper() or "5" in updates_arg[0]["range"]


# ============================================================================
# mark_dup_in_low (= scope1 都度マーク)
# ============================================================================

class TestMarkDupInLow:
    def test_only_matches_with_removed_keys_and_ai_column(self):
        """removed_canonical_keys と AI 列既書込みが一致した row のみ mark."""
        ws_high = _ws_with([HEADER, _row(item_id="ebay1", key="DW-5600")])
        ws_low = _ws_with([
            HEADER,
            _row(item_id="", title="r2_match", sold="", category="G-shock", key="DW-5600"),  # match
            _row(item_id="", title="r3_no_match", sold="", category="G-shock", key="DW-9999"),  # 不一致
            _row(item_id="", title="r4_no_ai", sold="", category="G-shock", key=""),  # AI空 → scope1 では skip
            _row(item_id="x", title="r5_b_non_empty", sold="", category="G-shock", key="DW-5600"),  # B非空
        ])
        result = dup_marker.mark_dup_in_low(
            ws_high, ws_low,
            removed_canonical_keys=["DW-5600"],
            dry_run=True,
        )
        assert result["marked"] == 1
        # row 2 (= header + 1) のみ
        assert any("r2_match" in s for s in result["sample"])


# ============================================================================
# fullscan_dup_mark (= scope2 初回フルスキャン)
# ============================================================================

class TestFullscanDupMark:
    def test_resolver_called_for_ai_empty_rows(self):
        """AI 列空 row は resolver で解決 → 既存と一致なら mark."""
        ws_high = _ws_with([HEADER, _row(item_id="ebay1", key="DW-5600RL-1JF")])
        ws_low = _ws_with([
            HEADER,
            _row(url="u1", item_id="", title="CASIO G-Shock DW-5600RL-1JF", sold="", category="G-shock", key=""),
        ])
        # resolver mock: title から DW-5600RL-1JF を返す
        calls = []

        def mock_resolver(title, url, purpose, **kwargs):
            calls.append((title, url))
            if "DW-5600RL-1JF" in title:
                return "DW-5600RL-1JF"
            return ""

        result = dup_marker.fullscan_dup_mark(
            ws_high, ws_low,
            resolve_sheet_row_fn=mock_resolver,
            dry_run=True,
        )
        assert result["scanned"] == 1
        assert result["resolved"] == 1
        assert result["unresolved"] == 0
        assert result["matched_existing"] == 1
        assert result["marked"] == 1
        assert len(calls) == 1  # resolver 1 回呼出

    def test_ai_filled_uses_column_value(self):
        """AI 列既書込みなら resolver 呼ばずに既書込み値採用 (= scope2 高速化)."""
        ws_high = _ws_with([HEADER, _row(item_id="x", key="DW-5600RL-1JF")])
        ws_low = _ws_with([
            HEADER,
            _row(url="u1", item_id="", title="t1", sold="", category="G-shock", key="DW-5600RL-1JF"),
        ])
        calls = []

        def mock_resolver(**kwargs):
            calls.append(kwargs)
            return "never_called"

        result = dup_marker.fullscan_dup_mark(
            ws_high, ws_low,
            resolve_sheet_row_fn=mock_resolver,
            dry_run=True,
        )
        assert result["matched_existing"] == 1
        assert len(calls) == 0  # AI 列既書込み row は resolver 不要

    def test_unresolved_not_marked(self):
        """resolver "" 返却 → mark 対象外 (= fail-closed)."""
        ws_high = _ws_with([HEADER, _row(item_id="x", key="DW-5600")])
        ws_low = _ws_with([
            HEADER,
            _row(url="u1", item_id="", title="unknown gibberish", sold="", category="G-shock", key=""),
        ])

        def mock_resolver(**kwargs):
            return ""

        result = dup_marker.fullscan_dup_mark(
            ws_high, ws_low,
            resolve_sheet_row_fn=mock_resolver,
            dry_run=True,
        )
        assert result["unresolved"] == 1
        assert result["marked"] == 0
