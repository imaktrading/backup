# -*- coding: utf-8 -*-
"""買えない仕入元の台帳と補URL消込の日別本数をスプシへ写す (2026-09-28 ADV 依頼).

LAPTOP の台帳ファイルはメインPC に届かないので、出品くんが読むタブへ写す。
タブの形 (列・種類の名前) は出品くん側 (iMakHQ tools/mercari_psa_resource.tab_rows_by_kind) と揃える。
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import not_buyable_tab_sync as nbt  # noqa: E402

pytestmark = pytest.mark.offline


def test_tab_rows_match_the_reader_format():
    rows = nbt.build_tab_rows(
        {"https://m/a": {"why": "売り切れ", "at": "2026-09-28T01:00:00"}},
        {"https://m/b": {"why": "売り切れ (再入荷あり)", "at": "2026-09-28T02:00:00"}})
    assert rows[0] == ["url", "種類", "理由", "日時", "書いた担当"]
    assert rows[1] == ["https://m/a", "not_buyable", "売り切れ", "2026-09-28T01:00:00", "監視くん(LAPTOP)"]
    assert rows[2][:2] == ["https://m/b", "restockable"]


def test_url_in_both_ledgers_is_written_once_as_not_buyable():
    """二度と出さない方を残す (安全側)."""
    rows = nbt.build_tab_rows({"https://m/x": {}}, {"https://m/x": {}})
    assert [r[:2] for r in rows[1:]] == [["https://m/x", "not_buyable"]]


def test_blank_urls_and_odd_values_are_skipped():
    rows = nbt.build_tab_rows({" ": {}, "https://m/a": "not-a-dict"}, None)
    assert [r[:2] for r in rows[1:]] == [["https://m/a", "not_buyable"]]


def test_clear_daily_counts_per_day_in_date_order():
    lines = [json.dumps({"ts": "2026/09/28 17:23:54"}),
             json.dumps({"ts": "2026/09/27 04:46:28"}),
             json.dumps({"ts": "2026/09/28 01:00:00"}),
             "{broken", json.dumps({"no_ts": 1})]
    assert nbt.build_clear_daily_rows(lines) == [["日付", "消した本数"],
                                                 ["2026-09-27", 1], ["2026-09-28", 2]]


def test_sync_does_not_raise_when_sheet_is_unreachable(tmp_path, monkeypatch):
    """スプシに書けなくても巡回は止めない (結果に error を書くだけ)."""
    nb = tmp_path / "nb.json"
    nb.write_text(json.dumps({"https://m/a": {"why": "x"}}), encoding="utf-8")
    import sheet_updater
    monkeypatch.setattr(sheet_updater, "open_sheet_by_id",
                        lambda _id: (_ for _ in ()).throw(RuntimeError("offline")))
    r = nbt.sync(nb, tmp_path / "missing.json", tmp_path / "missing.jsonl")
    assert r["not_buyable"] == 1 and r["restockable"] == 0 and r["clear_days"] == 0
    assert "offline" in r["error"]
