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
