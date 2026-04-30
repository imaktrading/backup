"""Phase 8 backup unit test (D 列バックアップ + 差分 + 復元 helpers).

gspread / Selenium は呼ばず、純粋な helper logic を offline 化する。
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ============================================================================
# 8a: backup tab name 正規表現 / pruning (運用シート保護)
# ============================================================================
def test_backup_tab_name_regex_matches_valid():
    """backup_YYYYMMDD_HHMMSS のみ match."""
    from backup import BACKUP_TAB_NAME_RE
    assert BACKUP_TAB_NAME_RE.match("backup_20260430_140000")
    assert BACKUP_TAB_NAME_RE.match("backup_20991231_235959")


def test_backup_tab_name_regex_rejects_non_backup():
    """listings / audit / Sheet1 等の運用シート名は拒否 (誤削除防止)."""
    from backup import BACKUP_TAB_NAME_RE
    assert not BACKUP_TAB_NAME_RE.match("商品管理シート")
    assert not BACKUP_TAB_NAME_RE.match("audit")
    assert not BACKUP_TAB_NAME_RE.match("Sheet1")
    assert not BACKUP_TAB_NAME_RE.match("backup_")
    assert not BACKUP_TAB_NAME_RE.match("backup_20260430")  # 時刻なし
    assert not BACKUP_TAB_NAME_RE.match("backup_20260430_14")  # 桁不足
    assert not BACKUP_TAB_NAME_RE.match("backup_x20260430_140000")
    assert not BACKUP_TAB_NAME_RE.match("my_backup_20260430_140000")


def test_list_backup_tabs_sorts_descending():
    """list_backup_tabs は ts 降順 (新しい順) で返す."""
    from backup import list_backup_tabs
    sh = MagicMock()
    ws_old = MagicMock(); ws_old.title = "backup_20260101_120000"; ws_old.id = 1
    ws_new = MagicMock(); ws_new.title = "backup_20260430_140000"; ws_new.id = 2
    ws_mid = MagicMock(); ws_mid.title = "backup_20260301_080000"; ws_mid.id = 3
    ws_other = MagicMock(); ws_other.title = "audit"; ws_other.id = 99
    sh.worksheets.return_value = [ws_old, ws_new, ws_mid, ws_other]
    tabs = list_backup_tabs(sh)
    # audit は除外
    assert len(tabs) == 3
    # 新しい順
    assert [t["title"] for t in tabs] == [
        "backup_20260430_140000",
        "backup_20260301_080000",
        "backup_20260101_120000",
    ]


def test_prune_old_backups_keeps_max_keep_and_only_deletes_backup_tabs():
    """prune は max_keep 件まで残し、backup_* 以外は絶対削除しない."""
    from backup import prune_old_backups
    sh = MagicMock()
    ws_list = []
    # 30 件 backup + 1 件 audit
    for i in range(30, 0, -1):
        w = MagicMock(); w.title = f"backup_2026{i:02d}01_120000"; w.id = i
        ws_list.append(w)
    audit = MagicMock(); audit.title = "audit"; audit.id = 9999
    ws_list.append(audit)
    sh.worksheets.return_value = ws_list

    # sh.worksheet(name) → match する mock を返す
    name_to_ws = {w.title: w for w in ws_list}
    sh.worksheet = lambda name: name_to_ws[name]
    deleted_titles = []
    sh.del_worksheet = lambda w: deleted_titles.append(w.title)

    r = prune_old_backups(sh, max_keep=24)
    assert r["deleted"] == 6  # 30 - 24
    # 全部 backup_ プレフィックス
    assert all(t.startswith("backup_") for t in deleted_titles)
    # audit は絶対削除されない
    assert "audit" not in deleted_titles


def test_prune_old_backups_under_max_keep_does_nothing():
    from backup import prune_old_backups
    sh = MagicMock()
    ws_list = []
    for i in range(5):
        w = MagicMock(); w.title = f"backup_2026010{i+1}_120000"; w.id = i
        ws_list.append(w)
    sh.worksheets.return_value = ws_list
    sh.del_worksheet = MagicMock()
    r = prune_old_backups(sh, max_keep=24)
    assert r["deleted"] == 0
    sh.del_worksheet.assert_not_called()


# ============================================================================
# 8b: D 列差分計算 + markdown 出力
# ============================================================================
def test_compute_d_diff_newly_sold():
    """空 → ○ を newly_sold として抽出."""
    from backup import compute_d_diff
    before = [
        {"row_index": 2, "current_sold": "", "url": "u2", "item_id": "i2", "title": "t2"},
        {"row_index": 3, "current_sold": "○", "url": "u3", "item_id": "i3", "title": "t3"},
    ]
    after = [
        {"row_index": 2, "current_sold": "○", "url": "u2", "item_id": "i2", "title": "t2"},
        {"row_index": 3, "current_sold": "○", "url": "u3", "item_id": "i3", "title": "t3"},
    ]
    diff = compute_d_diff(before, after)
    assert len(diff["newly_sold"]) == 1
    assert diff["newly_sold"][0]["row"] == 2
    assert len(diff["newly_in_stock"]) == 0
    assert diff["unchanged_count"] == 1


def test_compute_d_diff_newly_in_stock():
    """○ → 空 を newly_in_stock として抽出 (誤復活疑い)."""
    from backup import compute_d_diff
    before = [{"row_index": 5, "current_sold": "○", "url": "u5", "item_id": "i5", "title": "t5"}]
    after = [{"row_index": 5, "current_sold": "", "url": "u5", "item_id": "i5", "title": "t5"}]
    diff = compute_d_diff(before, after)
    assert len(diff["newly_sold"]) == 0
    assert len(diff["newly_in_stock"]) == 1
    assert diff["newly_in_stock"][0]["row"] == 5


def test_compute_d_diff_no_change():
    """○ → ○ / 空 → 空 はカウントしない."""
    from backup import compute_d_diff
    before = [
        {"row_index": 2, "current_sold": "", "url": "u", "item_id": "i", "title": "t"},
        {"row_index": 3, "current_sold": "○", "url": "u", "item_id": "i", "title": "t"},
    ]
    after = [
        {"row_index": 2, "current_sold": "", "url": "u", "item_id": "i", "title": "t"},
        {"row_index": 3, "current_sold": "○", "url": "u", "item_id": "i", "title": "t"},
    ]
    diff = compute_d_diff(before, after)
    assert diff["newly_sold"] == []
    assert diff["newly_in_stock"] == []
    assert diff["unchanged_count"] == 2


def test_render_diff_md_contains_counts_and_rows():
    """markdown に件数 + 各行情報が含まれる."""
    from backup import render_diff_md
    diff = {
        "newly_sold": [{"row": 10, "url": "u10", "item_id": "i10", "title": "t10"}],
        "newly_in_stock": [{"row": 20, "url": "u20", "item_id": "i20", "title": "t20"}],
        "unchanged_count": 100,
    }
    md = render_diff_md(diff, sheet_label="HIGH", cycle_ts="20260430_140000")
    assert "HIGH" in md
    assert "20260430_140000" in md
    assert "**1 件**" in md  # newly_sold
    assert "100" in md  # unchanged
    assert "i10" in md
    assert "i20" in md


def test_render_diff_md_zero_diff():
    """差分 0 件でも markdown 生成は失敗しない."""
    from backup import render_diff_md
    diff = {"newly_sold": [], "newly_in_stock": [], "unchanged_count": 421}
    md = render_diff_md(diff, sheet_label="LOW", cycle_ts="20260430_140000")
    assert "**0 件**" in md
    assert "newly_sold" in md  # section header may exist or not, but counts always


# ============================================================================
# 8c: 復元 - schema mismatch / dry_run 動作
# ============================================================================
def test_restore_from_backup_schema_mismatch_error():
    """backup tab の header が壊れていれば error 返却 (書込なし)."""
    from backup import restore_from_backup
    sh = MagicMock()
    backup_ws = MagicMock()
    backup_ws.get_all_values.return_value = [["wrong", "header"]]
    sh.worksheet = MagicMock(return_value=backup_ws)
    out = restore_from_backup(sh, "backup_20260430_140000", dry_run=True)
    assert out["error"] is not None
    assert "schema" in out["error"]
    assert out["applied"] is False
    assert out["to_restore"] == 0


def test_restore_from_backup_dry_run_no_writes():
    """dry_run=True ならスプシ書込せず差分のみ計算."""
    from backup import restore_from_backup, BACKUP_HEADERS
    sh = MagicMock()
    # backup tab: row 2,3 のスナップショット (row 2 が ○、row 3 が 空)
    backup_ws = MagicMock()
    backup_ws.get_all_values.return_value = [
        BACKUP_HEADERS,
        [2, "i2", "u2", "○", "20260430_140000"],
        [3, "i3", "u3", "", "20260430_140000"],
    ]
    # listings の現状: row 2 が 空、row 3 が ○ (両方差分あり)
    listings_ws = MagicMock()
    listings_ws.get_all_values.return_value = [
        ["URL", "itemID", "Title", "売り切れ", "状態", "価格"],
        ["u2", "i2", "t2", "", "", ""],   # row 2
        ["u3", "i3", "t3", "○", "", ""],  # row 3
    ]
    # sh.worksheet for backup 名 + listings (gid 経由)
    sh.worksheet = MagicMock(return_value=backup_ws)
    sh.get_worksheet_by_id = MagicMock(return_value=listings_ws)
    # sheet_updater.get_listings_worksheet 内で worksheets() iteration されるので
    sh.worksheets = MagicMock(return_value=[listings_ws])
    listings_ws.id = 851100680  # LISTINGS_GID

    out = restore_from_backup(sh, "backup_20260430_140000", dry_run=True)
    # 2 件差分
    assert out["error"] is None
    assert out["to_restore"] == 2
    assert out["applied"] is False
    # listings 側の更新メソッドは呼ばれない
    listings_ws.batch_update.assert_not_called()


# ============================================================================
# integration: run_cycle imports backup helpers
# ============================================================================
def test_run_cycle_imports_backup_module():
    """run_cycle.py が backup helpers を import している."""
    import run_cycle
    assert hasattr(run_cycle, "_resolve_backup_targets")
    assert hasattr(run_cycle, "_phase_compute_diff")
    # backup module functions が import されている
    src = Path(run_cycle.__file__).read_text(encoding="utf-8")
    assert "from backup import" in src
    assert "backup_d_column" in src
    assert "compute_d_diff" in src


def test_control_panel_has_restore_section():
    """control_panel に Phase 8c 復元セクションが追加されている."""
    cp_path = ROOT / "control_panel.py"
    src = cp_path.read_text(encoding="utf-8")
    assert "_restore_load_backups" in src
    assert "_restore_preview" in src
    assert "_restore_apply" in src
    assert "スプシ復元" in src


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
