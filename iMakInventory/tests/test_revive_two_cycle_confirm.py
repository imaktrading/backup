"""復活 2 cycle 連続確定 state の regression test (2026-08-07 revive_qty1_impl §6).

依頼書 前提: 「delta="newly_in_stock" は 1 cycle で立つが、 2 cycle 連続で in_stock
確定した行だけ pending_revive に enqueue する (誤検知1回で誤復活しない)」

confirm_and_enqueue_revive() の遷移:
  - 1 cycle 目 newly_in_stock: state に first_seen 記録、 pending_revive には積まない
  - 2 cycle 目も in_stock:     state から削除、 pending_revive に enqueue (promoted)
  - 2 cycle 目に is_sold=True: state から削除 (幻の in_stock を持ち越さない)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import monitor_listings as ML  # noqa: E402


def _r(iid, delta, is_sold, current_sold=""):
    return {
        "row_index": 100,
        "url": "https://amazon.co.jp/dp/B00000000X",
        "item_id": iid,
        "title": iid,
        "supplier": "amazon",
        "raw_status": "IN_STOCK" if is_sold is False else "SOLD",
        "is_sold": is_sold,
        "delta": delta,
        "current_sold": current_sold,
    }


def test_first_cycle_newly_in_stock_does_not_enqueue(tmp_path, monkeypatch):
    """1 cycle 目 newly_in_stock は state に記録、 pending_revive には入らない。"""
    # tmp_path に state file と pending を作る (本番と隔離)
    monkeypatch.setattr(ML, "PENDING_REVIVE_FILE", tmp_path / "pending_revive.jsonl")
    monkeypatch.setattr(ML, "NEWLY_IN_STOCK_STATE_FILE",
                        tmp_path / "newly_in_stock_state.json")
    monkeypatch.setattr(ML, "DECISION_LOG_DIR", tmp_path)

    results = [_r("IID_ONE", delta="newly_in_stock", is_sold=False)]
    stats = ML.confirm_and_enqueue_revive("HIGH", results, dry_run=False)
    assert stats["first_seen"] == 1
    assert stats["promoted"] == 0
    assert not (tmp_path / "pending_revive.jsonl").exists()
    state = json.loads((tmp_path / "newly_in_stock_state.json").read_text(encoding="utf-8"))
    assert "IID_ONE" in state["HIGH"]
    assert state["HIGH"]["IID_ONE"]["cycles"] == 1


def test_second_cycle_confirms_and_enqueues(tmp_path, monkeypatch):
    """1 cycle 目 first_seen 後、 2 cycle 目でも in_stock なら enqueue + state 削除。"""
    pending_p = tmp_path / "pending_revive.jsonl"
    state_p = tmp_path / "newly_in_stock_state.json"
    monkeypatch.setattr(ML, "PENDING_REVIVE_FILE", pending_p)
    monkeypatch.setattr(ML, "NEWLY_IN_STOCK_STATE_FILE", state_p)
    monkeypatch.setattr(ML, "DECISION_LOG_DIR", tmp_path)

    # 1 cycle 目
    ML.confirm_and_enqueue_revive("HIGH",
                                    [_r("IID_TWO", "newly_in_stock", False)],
                                    dry_run=False)
    # 2 cycle 目: 同じ item が in_stock 継続 (delta=unchanged, D=空)
    stats = ML.confirm_and_enqueue_revive("HIGH",
                                            [_r("IID_TWO", "unchanged", False,
                                                current_sold="")],
                                            dry_run=False)
    assert stats["promoted"] == 1
    assert pending_p.exists()
    lines = [json.loads(l) for l in pending_p.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lines) == 1
    assert lines[0]["item_id"] == "IID_TWO"
    # state から削除されている (2 cycle 確定で消える)
    state = json.loads(state_p.read_text(encoding="utf-8"))
    assert "IID_TWO" not in state.get("HIGH", {})


def test_second_cycle_sold_clears_state(tmp_path, monkeypatch):
    """1 cycle 目 first_seen 後、 2 cycle 目で is_sold=True → state 削除、 enqueue しない
    (幻の in_stock を持ち越さない)。"""
    pending_p = tmp_path / "pending_revive.jsonl"
    state_p = tmp_path / "newly_in_stock_state.json"
    monkeypatch.setattr(ML, "PENDING_REVIVE_FILE", pending_p)
    monkeypatch.setattr(ML, "NEWLY_IN_STOCK_STATE_FILE", state_p)
    monkeypatch.setattr(ML, "DECISION_LOG_DIR", tmp_path)

    ML.confirm_and_enqueue_revive("HIGH",
                                    [_r("IID_FLAKY", "newly_in_stock", False)],
                                    dry_run=False)
    # 2 cycle 目 in_stock 逆転 → 幻の in_stock を state から掃除
    stats = ML.confirm_and_enqueue_revive("HIGH",
                                            [_r("IID_FLAKY", "newly_sold", True,
                                                current_sold="")],
                                            dry_run=False)
    assert stats["promoted"] == 0
    assert stats["cleared"] == 1
    assert not pending_p.exists()
    state = json.loads(state_p.read_text(encoding="utf-8"))
    assert "IID_FLAKY" not in state.get("HIGH", {})


def test_uncertain_result_preserves_state(tmp_path, monkeypatch):
    """判定不能 (is_sold=None / delta=uncertain) は state に触らない (前状態温存)。"""
    pending_p = tmp_path / "pending_revive.jsonl"
    state_p = tmp_path / "newly_in_stock_state.json"
    monkeypatch.setattr(ML, "PENDING_REVIVE_FILE", pending_p)
    monkeypatch.setattr(ML, "NEWLY_IN_STOCK_STATE_FILE", state_p)
    monkeypatch.setattr(ML, "DECISION_LOG_DIR", tmp_path)

    ML.confirm_and_enqueue_revive("HIGH",
                                    [_r("IID_STAY", "newly_in_stock", False)],
                                    dry_run=False)
    stats = ML.confirm_and_enqueue_revive("HIGH",
                                            [{"row_index": 100, "item_id": "IID_STAY",
                                              "url": "u", "title": "t",
                                              "is_sold": None, "delta": "uncertain",
                                              "current_sold": ""}],
                                            dry_run=False)
    assert stats["promoted"] == 0
    assert stats["stayed"] == 1
    state = json.loads(state_p.read_text(encoding="utf-8"))
    assert "IID_STAY" in state.get("HIGH", {})


def test_dry_run_does_not_write_state_or_pending(tmp_path, monkeypatch):
    """dry_run=True: state も pending も書かない (queue 汚染防止)。"""
    pending_p = tmp_path / "pending_revive.jsonl"
    state_p = tmp_path / "newly_in_stock_state.json"
    monkeypatch.setattr(ML, "PENDING_REVIVE_FILE", pending_p)
    monkeypatch.setattr(ML, "NEWLY_IN_STOCK_STATE_FILE", state_p)
    monkeypatch.setattr(ML, "DECISION_LOG_DIR", tmp_path)

    ML.confirm_and_enqueue_revive("HIGH",
                                    [_r("IID_DRY", "newly_in_stock", False)],
                                    dry_run=True)
    # state は書かれない (実巡回時に始めて記録される)
    assert not state_p.exists()
    assert not pending_p.exists()
