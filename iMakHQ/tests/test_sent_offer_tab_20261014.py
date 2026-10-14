"""送ったオファーを「既存メンテ」タブ 送ったオファー に書く (2026-10-14 ブラボー GO B-20261014-014)。"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
import shelf_offer as SO  # noqa: E402


def test_mark_sent_appends_to_sent_tab(tmp_path, monkeypatch):
    p = tmp_path / "offers.json"
    monkeypatch.setattr(SO, "OFFERS_PATH", str(p))
    SO.save_json(str(p), {"X": {"status": SO.WAITING}})
    got = []
    monkeypatch.setattr(SO, "sent_tab_append", lambda rows, log=print: got.extend(rows) or len(rows))
    assert SO.mark_sent("X", 8)["ok"]
    assert got and got[0][0] == "X" and got[0][2]          # itemID / 送った時刻 / 期限


def test_no_real_sheet_write_in_tests():
    assert SO.sent_tab_append([["X", "t", "e"]], log=lambda m: None) == 0
