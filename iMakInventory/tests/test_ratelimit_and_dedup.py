"""07-04〜07 取下げ漏れ蓄積事故の再発防止 regression (2026-07-07).

事故: 07-04 eBay Trading API 518 "Call usage limit" → 取下げ失敗が action-needed 扱いで
大量発生 → 急増ガードが pending の同一 item を毎 cycle HOLD (action_required へ dedup 無し
追記) で deadlock 化 + ファイル肥大 (335 item / 2227 entry) → 5 日で取下げ漏れ 24 件蓄積。

修正2点:
1. 518 = rate_limited = transient 扱い (action-needed から除外)。 ただし success=False は
   維持 (item は live のまま pending 残置で次 cycle 自動 retry、 取下げ義務 persist)。
2. append_action_required を (item_id, reason) で冪等化 (= 毎 cycle 再追記の重複肥大を根絶)。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ---- Fix 1: 518 rate-limit 分類 ----
def test_518_is_rate_limited():
    from ebay_actions.trading_api_uploader import _is_rate_limited
    # error_code / message どちらでも検出
    assert _is_rate_limited({"success": False, "error_code": "518",
                             "error_message": "Call usage limit has been reached."}) is True
    assert _is_rate_limited({"success": False, "error_code": "",
                             "error_message": "Call usage limit has been reached."}) is True


def test_518_not_confused_with_success_or_other_failures():
    from ebay_actions.trading_api_uploader import _is_rate_limited
    # 成功は rate_limited でない
    assert _is_rate_limited({"success": True, "error_code": "518"}) is False
    # 他の failure (safe failure 等) は rate_limited でない
    assert _is_rate_limited({"success": False, "error_code": "21916750",
                             "error_message": "FixedPrice item ended"}) is False
    assert _is_rate_limited({"success": False, "error_code": "231",
                             "error_message": "Item not found"}) is False


# ---- Fix 2: append_action_required 冪等化 ----
def _result(item_id, row=10):
    return {"row_index": row, "url": f"https://x/{item_id}", "item_id": item_id,
            "title": "t", "supplier": "mercari", "raw_status": "newly_sold_burst_holdout"}


def _count_entries(path):
    return sum(1 for l in path.read_text(encoding="utf-8").splitlines() if l.strip())


def test_append_action_required_dedup(tmp_path, monkeypatch):
    import monitor_listings as M
    f = tmp_path / "action_required.jsonl"
    monkeypatch.setattr(M, "ACTION_REQUIRED_FILE", f)
    monkeypatch.setattr(M, "DECISION_LOG_DIR", tmp_path)
    # 同一 (item_id, reason) を 5 回追記 → 1 件のみ
    for _ in range(5):
        M.append_action_required("SHEET", _result("358000000001"),
                                 reason="newly_sold_burst_guard_holdout", dry_run=False)
    assert _count_entries(f) == 1, "同一 item の重複追記が dedup されていない (= deadlock 肥大の再発)"


def test_append_action_required_distinct_items_and_reasons_kept(tmp_path, monkeypatch):
    import monitor_listings as M
    f = tmp_path / "action_required.jsonl"
    monkeypatch.setattr(M, "ACTION_REQUIRED_FILE", f)
    monkeypatch.setattr(M, "DECISION_LOG_DIR", tmp_path)
    M.append_action_required("SHEET", _result("A"), reason="newly_sold_burst_guard_holdout", dry_run=False)
    M.append_action_required("SHEET", _result("B"), reason="newly_sold_burst_guard_holdout", dry_run=False)
    # 別 item は残る
    assert _count_entries(f) == 2
    # 同 item でも reason が違えば別 (= 取りこぼし防止)
    M.append_action_required("SHEET", _result("A"), reason="verify_qty_gt0_giveup", dry_run=False)
    assert _count_entries(f) == 3
    # item_id 空欄は row_index で dedup (異なる row は別)
    M.append_action_required("SHEET", {"row_index": 55, "url": "u", "item_id": "", "raw_status": ""},
                             reason="item_id_empty", dry_run=False)
    M.append_action_required("SHEET", {"row_index": 55, "url": "u", "item_id": "", "raw_status": ""},
                             reason="item_id_empty", dry_run=False)
    assert _count_entries(f) == 4  # row55 は 1 件だけ


# ============================================================================
# Root fix (2026-07-09 再発): cycle 外取下げ済 (D=○ × eBay qty=0) の pending prune
#   = 急増ガード誤発火 deadlock の構造的原因を断つ。 fail-CLOSED を失敗注入で検証。
# ============================================================================
def _cand(item_id, row=10):
    return {"sheet_label": "HIGH", "row_index": row, "item_id": item_id,
            "url": f"https://x/{item_id}", "title": "t", "current_sold": "○"}


def test_prune_qty_map_zero_is_pruned_positive_is_kept():
    """qty_map: qty=0 → prune (drain 対象) / qty>0 → 温存 (取下げ義務 persist)。"""
    from ebay_actions.revise_csv_generator import prune_taken_down_candidates
    cands = [_cand("A"), _cand("B"), _cand("C")]
    qty_map = {"A": 0, "B": 3, "C": 0}
    live, drained, unknown = prune_taken_down_candidates(cands, qty_map=qty_map)
    assert sorted(drained) == ["A", "C"], "eBay qty=0 が drain 対象になっていない"
    assert [c["item_id"] for c in live] == ["B"], "qty>0 の live 品が温存されていない"
    assert unknown == 0


def test_prune_absent_from_map_confirmed_via_getitem(monkeypatch):
    """map 不在は GetItem で確定。 部分取得 map での誤 prune (fail-OPEN) を防ぐ核。"""
    import ebay_actions.revise_csv_generator as R
    # A は map 不在 & GetItem=0 (ended) → prune。 B は map 不在 & GetItem=5 → 温存。
    getitem = {"A": 0, "B": 5}
    monkeypatch.setattr(R, "_ebay_current_qty", lambda iid, tok: getitem.get(iid))
    live, drained, unknown = R.prune_taken_down_candidates(
        [_cand("A"), _cand("B")], qty_map={}, token="tok")
    assert drained == ["A"], "map 不在 & ended を GetItem で prune できていない"
    assert [c["item_id"] for c in live] == ["B"]
    assert unknown == 0


def test_prune_api_failure_is_kept_failclosed(monkeypatch):
    """GetItem が None (API 失敗/qty 不明) → 温存 (fail-CLOSED)。 誤 prune=fail-OPEN 禁止。"""
    import ebay_actions.revise_csv_generator as R
    monkeypatch.setattr(R, "_ebay_current_qty", lambda iid, tok: None)
    live, drained, unknown = R.prune_taken_down_candidates(
        [_cand("A"), _cand("B")], qty_map={}, token="tok")
    assert drained == [], "API 失敗品を誤って drain した (fail-OPEN)"
    assert len(live) == 2, "判定不能品を温存していない"
    assert unknown == 2


def test_prune_empty_item_id_is_kept():
    """item_id 空欄は判定不能 → 温存 (fail-CLOSED)。"""
    from ebay_actions.revise_csv_generator import prune_taken_down_candidates
    live, drained, unknown = prune_taken_down_candidates(
        [_cand(""), _cand("A")], qty_map={"A": 0})
    assert drained == ["A"]
    assert [c["item_id"] for c in live] == [""]


def test_prune_breaks_surge_guard_deadlock():
    """deadlock 再現: 35 candidates のうち 20 が取下げ済 (qty=0) → prune 後 15 件。
    急増ガード閾値 (30) を下回り HOLD 誤発火しない = deadlock が解ける。"""
    from ebay_actions.revise_csv_generator import (
        prune_taken_down_candidates, DEFAULT_NEWLY_SOLD_BURST_THRESHOLD,
    )
    done = [_cand(f"DONE{i}", row=i) for i in range(20)]      # 取下げ済
    live_items = [_cand(f"LIVE{i}", row=100 + i) for i in range(15)]  # 本物 live
    qty_map = {**{f"DONE{i}": 0 for i in range(20)},
               **{f"LIVE{i}": 1 for i in range(15)}}
    live, drained, _ = prune_taken_down_candidates(done + live_items, qty_map=qty_map)
    assert len(drained) == 20
    assert len(live) == 15
    # prune 前 (35) は閾値超で全 HOLD だったが、 prune 後 (15) は閾値以下 → 正常 upload へ
    assert len(done + live_items) > DEFAULT_NEWLY_SOLD_BURST_THRESHOLD
    assert len(live) <= DEFAULT_NEWLY_SOLD_BURST_THRESHOLD
