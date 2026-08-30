"""test が本番の台帳に書き込まないこと — 2026-08-30.

事故: test が本番の pending_revise.jsonl に item_id="a"/"b"/"new1" 等を書き、
実在しない itemID なので eBay 照会が毎回失敗 → 取下げツールが恒久的に
「未完了が残っています」と言い続けた。**警告が嘘をつく**状態は、本物の
取下げ漏れをその中に埋もれさせる (一番避けたい失敗)。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import monitor_listings as ml  # noqa: E402


def _result(iid):
    return {"row_index": 1, "url": "https://x/y", "item_id": iid, "title": "t",
            "supplier": "mercari", "raw_status": "SOLD_OUT"}


def test_append_goes_to_testrun_file_not_production():
    """★ この test 自体が本番キューを汚さないことの証明でもある."""
    prod = ml.PENDING_REVISE_FILE
    before = prod.read_text(encoding="utf-8") if prod.exists() else ""

    ml.append_pending_revise("HIGH", _result("TEST_SHOULD_NOT_LEAK"), dry_run=False)

    after = prod.read_text(encoding="utf-8") if prod.exists() else ""
    assert after == before, "本番の取下げキューに test の entry が入った"
    testrun = ml._ledger_path(prod)
    assert testrun.name.endswith("_TESTRUN.jsonl")
    assert "TEST_SHOULD_NOT_LEAK" in testrun.read_text(encoding="utf-8")


def test_patched_path_is_left_alone(tmp_path):
    """test が tmp に差し替えた時は、その tmp にそのまま書く (二重に化けない)."""
    p = tmp_path / "pending_revise.jsonl"
    assert ml._ledger_path(p) == p


def test_production_path_unchanged_outside_pytest(monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    assert ml._ledger_path(ml.PENDING_REVISE_FILE) == ml.PENDING_REVISE_FILE


def test_read_pending_reads_the_same_file_it_writes():
    ml.append_pending_revise("HIGH", _result("ROUNDTRIP_ID"), dry_run=False)
    assert "ROUNDTRIP_ID" in ml.read_pending_item_ids()
