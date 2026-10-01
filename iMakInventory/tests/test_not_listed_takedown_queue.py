# -*- coding: utf-8 -*-
"""itemID="9999" (= 出品しないと決めた行) を取下げ待ちに残さない (2026-10-01 HQ 依頼).

9999 は 2026-09-21 ユーザー決定の「出品しない確定」の印で、シートからは消さない。
eBay に出品が無いので状態が取れず、取下げ待ちに毎時「未完了」として残り続けていた。
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

pytestmark = pytest.mark.offline


def _res(item_id):
    return {"row_index": 203, "url": "https://www.amazon.co.jp/dp/X", "item_id": item_id,
            "title": "t", "supplier": "amazon", "raw_status": "sold_out"}


def test_not_listed_row_is_not_enqueued(tmp_path):
    import monitor_listings as ml
    pending = tmp_path / "pending_revise.jsonl"
    with patch.object(ml, "PENDING_REVISE_FILE", pending):
        ml.append_pending_revise("SHEET", _res("9999"), dry_run=False)
        ml.append_pending_revise("SHEET", _res("820000000001"), dry_run=False)
    ids = [json.loads(l)["item_id"] for l in pending.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert ids == ["820000000001"]


def test_existing_not_listed_entries_are_pruned_with_archive(tmp_path):
    import ebay_actions.revise_csv_generator as rg
    pending = tmp_path / "pending_revise.jsonl"
    discarded = tmp_path / "discarded_revise.jsonl"
    pending.write_text("\n".join(json.dumps({"item_id": i, "sheet": "SHEET"})
                                 for i in ("9999", "820000000001", " 9999 ")) + "\n", encoding="utf-8")
    with patch.object(rg, "PENDING_REVISE_FILE", pending), \
         patch.object(rg, "DISCARDED_REVISE_FILE", discarded):
        moved = rg.prune_not_listed_pending_revise()
    rest = [json.loads(l)["item_id"] for l in pending.read_text(encoding="utf-8").splitlines() if l.strip()]
    arch = [json.loads(l) for l in discarded.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert moved == 2
    assert rest == ["820000000001"]                       # 本物の取下げ待ちは残す
    assert {a["discard_reason"] for a in arch} == {"not_listed_item_id_9999"}   # 証跡を残す


def test_prune_is_noop_without_queue(tmp_path):
    import ebay_actions.revise_csv_generator as rg
    with patch.object(rg, "PENDING_REVISE_FILE", tmp_path / "missing.jsonl"):
        assert rg.prune_not_listed_pending_revise() == 0
