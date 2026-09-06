"""棚卸レポート: 取り下げ済みを候補に出さない (2026-09-07)。

実害: 9/07 の「取り下げ候補 26 件」は全て 9/01 に取り下げ済みだった。
毎回 eBay に問い合わせて「既に終了済」と分かってから外していたので、
無駄な API を使い、報告も「対象 26 / 完了 3」と読めない形になっていた。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import stale_zero_report as sz  # noqa: E402


def _ledger(tmp_path, entries):
    p = tmp_path / "ended.jsonl"
    p.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries),
                 encoding="utf-8")
    return p


def test_ended_ids_are_collected(tmp_path, monkeypatch):
    monkeypatch.setattr(sz, "ENDED_LEDGER", _ledger(tmp_path, [
        {"item_id": "111", "verified_ok": True},
        {"item_id": "222", "verified_ok": False},     # 終了を確認できなかった → 候補に残す
    ]))
    assert sz.already_ended_ids() == {"111"}


def test_missing_ledger_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(sz, "ENDED_LEDGER", tmp_path / "none.jsonl")
    assert sz.already_ended_ids() == set()


def test_broken_ledger_keeps_all_candidates(tmp_path, monkeypatch):
    """履歴が壊れていたら「外さない」= 従来どおり全部候補 (安全側に倒す)."""
    p = tmp_path / "broken.jsonl"
    p.write_text("{ this is not json\n", encoding="utf-8")
    monkeypatch.setattr(sz, "ENDED_LEDGER", p)
    assert sz.already_ended_ids() == set()


def test_stuck_at_zero_counts_only_unbroken_zero_streak():
    """1 サイズでも復活したら日数はリセットされる (= 全枠売切の連続だけ数える)."""
    series = {
        "aaa": [("2026-08-01", 0), ("2026-08-05", 2), ("2026-08-10", 0), ("2026-09-07", 0)],
        "bbb": [("2026-08-01", 0), ("2026-09-07", 0)],
        "ccc": [("2026-08-01", 0), ("2026-09-07", 3)],   # 今 在庫あり → 候補外
    }
    out = {r["item_id"]: r for r in sz.stuck_at_zero(series, {})}
    assert out["aaa"]["zero_since"] == "2026-08-10"    # 8/05 の復活でリセット
    assert out["bbb"]["zero_since"] == "2026-08-01"
    assert "ccc" not in out
