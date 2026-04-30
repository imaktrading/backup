"""Phase 6 unit test (--sheet-id 単一スプシモード + control_panel helpers).

GUI Tkinter は手動動作確認のみ、pytest は CLI/helpers の物理担保。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ============================================================================
# 6a: --sheet-id 単一モード CLI 引数 解釈
# ============================================================================
def test_monitor_listings_cli_has_sheet_id_arg():
    """monitor_listings.py に --sheet-id / --sheet-label 引数が追加されている."""
    import argparse, monitor_listings
    # main 関数を見つけて argparse spy
    import re
    src = Path(monitor_listings.__file__).read_text(encoding="utf-8", errors="replace")
    assert "--sheet-id" in src
    assert "--sheet-label" in src
    assert "単一スプシ" in src or "single" in src.lower()


def test_revise_csv_generator_cli_has_sheet_id_arg():
    """revise_csv_generator にも --sheet-id 引数追加."""
    from ebay_actions import revise_csv_generator as rcg
    src = Path(rcg.__file__).read_text(encoding="utf-8", errors="replace")
    assert "--sheet-id" in src
    assert "single_sheet_id" in src


def test_run_cycle_has_sheet_id_param():
    """run_cycle.run_cycle が sheet_id / sheet_label 受ける."""
    from run_cycle import run_cycle
    import inspect
    sig = inspect.signature(run_cycle)
    assert "sheet_id" in sig.parameters
    assert "sheet_label" in sig.parameters
    assert "high_sheet_id" in sig.parameters
    assert "low_sheet_id" in sig.parameters


def test_run_cycle_has_monitor_only_param():
    """run_cycle.run_cycle が monitor_only flag 受ける."""
    from run_cycle import run_cycle
    import inspect
    sig = inspect.signature(run_cycle)
    assert "monitor_only" in sig.parameters
    # default False
    assert sig.parameters["monitor_only"].default is False


def test_control_panel_has_monitor_only_var():
    """control_panel に monitor_only checkbox 追加."""
    from pathlib import Path
    src = Path(__file__).resolve().parent.parent / "control_panel.py"
    content = src.read_text(encoding="utf-8")
    assert "monitor_only_var" in content
    assert "--monitor-only" in content
    assert "在庫チェックのみ" in content


def test_collect_from_pending_queue_has_single_params():
    """collect_from_pending_queue が single_sheet_id / single_sheet_label を受ける."""
    from ebay_actions.revise_csv_generator import collect_from_pending_queue
    import inspect
    sig = inspect.signature(collect_from_pending_queue)
    assert "single_sheet_id" in sig.parameters
    assert "single_sheet_label" in sig.parameters


# ============================================================================
# 6b: control_panel helpers
# ============================================================================
def test_push_history_dedup_and_max():
    """_push_history: 重複 dedup + 最新 5 件保持."""
    from control_panel import _push_history, HISTORY_MAX
    h = []
    h = _push_history(h, "a")
    h = _push_history(h, "b")
    h = _push_history(h, "a")  # dedup, "a" 先頭
    assert h == ["a", "b"]
    # 6 件入れて 5 件で切られるか
    h = []
    for v in "abcdef":
        h = _push_history(h, v)
    assert len(h) == HISTORY_MAX
    assert h[0] == "f"  # 最新が先頭


def test_push_history_empty_value_noop():
    """_push_history: 空文字は無視."""
    from control_panel import _push_history
    h = ["a", "b"]
    h2 = _push_history(h, "")
    assert h2 == h


def test_load_state_returns_dict_when_missing(tmp_path, monkeypatch):
    """_load_state: ファイル不在で空 dict 返す."""
    import control_panel as cp
    fake_state = tmp_path / ".gui_state.json"
    monkeypatch.setattr(cp, "GUI_STATE_FILE", fake_state)
    assert not fake_state.exists()
    state = cp._load_state()
    assert "high_history" in state
    assert "low_history" in state
    assert "single_history" in state


def test_save_load_state_roundtrip(tmp_path, monkeypatch):
    """_save_state → _load_state で値が保持される."""
    import control_panel as cp
    fake_state = tmp_path / ".gui_state.json"
    monkeypatch.setattr(cp, "GUI_STATE_FILE", fake_state)
    saved = {"high_history": ["A", "B"], "low_history": ["X"], "single_history": []}
    cp._save_state(saved)
    loaded = cp._load_state()
    assert loaded == saved


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
