"""要対応キューの閉じ処理 regression test.

★ 2026-08-17 制定。実害: 08-13 の revive 急増ガード HOLD で 22 件を要対応に積んだが、
その 22 件は同日〜08-16 に**全件 復活成功**していた。にもかかわらずキューから外す処理が
無かったため、5 日間「要対応 22件」と表示され続けた。要対応が嘘をつくと、本当に対処が
必要な項目が埋もれる (= 誰も見なくなる)。

仕様:
- 積んだ理由が解消したら閉じる。証跡は action_required_resolved.jsonl に残す (silent 削除しない)
- 別の reason で載っている entry は閉じない
- dry_run では件数だけ返し、ファイルは触らない
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import monitor_listings as ML  # noqa: E402


def _seed(tmp_path, entries):
    f = tmp_path / "action_required.jsonl"
    f.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in entries) + "\n",
                 encoding="utf-8")
    return f


@pytest.mark.offline
def test_resolved_entries_are_closed_and_archived(tmp_path):
    ar = _seed(tmp_path, [
        {"item_id": "A1", "reason": "revive_burst_guard_holdout", "row_index": 1},
        {"item_id": "A2", "reason": "revive_burst_guard_holdout", "row_index": 2},
        {"item_id": "B1", "reason": "item_id_empty", "row_index": 3},
    ])
    res = tmp_path / "action_required_resolved.jsonl"
    with patch.object(ML, "ACTION_REQUIRED_FILE", ar), \
         patch.object(ML, "ACTION_REQUIRED_RESOLVED_FILE", res):
        closed = ML.resolve_action_required(["A1", "A2"], "revive_burst_guard_holdout")
        rest = [json.loads(l) for l in ar.read_text(encoding="utf-8").splitlines() if l.strip()]
        arch = [json.loads(l) for l in res.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert closed == 2
    assert [e["item_id"] for e in rest] == ["B1"]          # 別 reason は残す
    assert {e["item_id"] for e in arch} == {"A1", "A2"}
    assert all(e.get("resolved_at") for e in arch)          # いつ閉じたかを残す


@pytest.mark.offline
def test_other_reason_same_item_is_kept(tmp_path):
    """同じ item_id でも reason が違うものは閉じない (別の要対応が消えると危険)."""
    ar = _seed(tmp_path, [
        {"item_id": "A1", "reason": "revive_burst_guard_holdout"},
        {"item_id": "A1", "reason": "verify_qty_gt0_giveup"},
    ])
    res = tmp_path / "action_required_resolved.jsonl"
    with patch.object(ML, "ACTION_REQUIRED_FILE", ar), \
         patch.object(ML, "ACTION_REQUIRED_RESOLVED_FILE", res):
        closed = ML.resolve_action_required(["A1"], "revive_burst_guard_holdout")
        rest = [json.loads(l) for l in ar.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert closed == 1
    assert [e["reason"] for e in rest] == ["verify_qty_gt0_giveup"]


@pytest.mark.offline
def test_dry_run_does_not_touch_files(tmp_path):
    ar = _seed(tmp_path, [{"item_id": "A1", "reason": "revive_burst_guard_holdout"}])
    before = ar.read_text(encoding="utf-8")
    res = tmp_path / "action_required_resolved.jsonl"
    with patch.object(ML, "ACTION_REQUIRED_FILE", ar), \
         patch.object(ML, "ACTION_REQUIRED_RESOLVED_FILE", res):
        closed = ML.resolve_action_required(["A1"], "revive_burst_guard_holdout", dry_run=True)
    assert closed == 1
    assert ar.read_text(encoding="utf-8") == before
    assert not res.exists()


@pytest.mark.offline
def test_empty_input_is_noop(tmp_path):
    ar = _seed(tmp_path, [{"item_id": "A1", "reason": "revive_burst_guard_holdout"}])
    with patch.object(ML, "ACTION_REQUIRED_FILE", ar):
        assert ML.resolve_action_required([], "revive_burst_guard_holdout") == 0
        assert ML.resolve_action_required(None, "revive_burst_guard_holdout") == 0
