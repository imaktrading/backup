"""売切済 (D=○) の行に後から itemID が入った出品を取下げ待ちに積む (2026-09-24).

実害: 9/9〜9/11 に D=○ の行へ itemID が入った4件 (820104169010 等) が、巡回の
「D=○ 1点もの skip」で newly_sold にならず、約2週間 eBay で買える状態のまま残った。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import monitor_listings as ML  # noqa: E402


def _row(iid):
    return {"row_index": 2383, "url": "https://jp.mercari.com/item/m41110147966",
            "item_id": iid, "title": "PSA10", "supplier": "mercari",
            "raw_status": "skipped_mercari_sold"}


def test_first_run_seeds_without_enqueue(tmp_path, monkeypatch):
    monkeypatch.setattr(ML, "SOLD_ROW_LISTED_SEEN_FILE", tmp_path / "seen.json")
    new, first = ML.newly_listed_on_sold_rows("SHEET", {"111": _row("111")})
    assert first is True and new == []


def test_itemid_added_to_sold_row_is_detected(tmp_path, monkeypatch):
    monkeypatch.setattr(ML, "SOLD_ROW_LISTED_SEEN_FILE", tmp_path / "seen.json")
    ML.save_sold_row_listed_seen("SHEET", {"111": _row("111")})
    cur = {"111": _row("111"), "820104169010": _row("820104169010")}
    new, first = ML.newly_listed_on_sold_rows("SHEET", cur)
    assert first is False and new == ["820104169010"]
    # 次の cycle では既知 = 二重に積まない
    ML.save_sold_row_listed_seen("SHEET", cur)
    assert ML.newly_listed_on_sold_rows("SHEET", cur) == ([], False)


def test_labels_are_independent(tmp_path, monkeypatch):
    monkeypatch.setattr(ML, "SOLD_ROW_LISTED_SEEN_FILE", tmp_path / "seen.json")
    ML.save_sold_row_listed_seen("SHEET", {"111": _row("111")})
    new, first = ML.newly_listed_on_sold_rows("LOW", {"111": _row("111")})
    assert first is True and new == []


def test_unsaved_run_keeps_it_pending(tmp_path, monkeypatch):
    """途中で落ちた cycle (保存されない) の後も、次の cycle で再び新規として出る."""
    monkeypatch.setattr(ML, "SOLD_ROW_LISTED_SEEN_FILE", tmp_path / "seen.json")
    ML.save_sold_row_listed_seen("SHEET", {})
    cur = {"820104169010": _row("820104169010")}
    assert ML.newly_listed_on_sold_rows("SHEET", cur)[0] == ["820104169010"]
    assert ML.newly_listed_on_sold_rows("SHEET", cur)[0] == ["820104169010"]


def test_broken_file_treated_as_first_run(tmp_path, monkeypatch):
    p = tmp_path / "seen.json"
    p.write_text("{broken", encoding="utf-8")
    monkeypatch.setattr(ML, "SOLD_ROW_LISTED_SEEN_FILE", p)
    assert ML.newly_listed_on_sold_rows("SHEET", {"1": _row("1")}) == ([], True)
