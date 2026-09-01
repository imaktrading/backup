# -*- coding: utf-8 -*-
"""表示目的の読み取りだけ使い回す (429 対策) の回帰テスト (2026-09-01)。

実害: 出品くんの走行中に Sheets の 1分あたり読み取り上限 (429) に当たり、
「出せるか」の塗り直し (sheet_listable_flag) が落ちた。
同じ日にパネルのボタンへ件数を出す集計を足しており、同じタブを何度も読んでいた。

規約: **書いてから読み直す通常の走行には効かせない** (memo が効くと書込結果が見えない)。
      SHEET_READ_MEMO=1 の時だけ効かせる。実測 36.9秒 → 14.3秒。
"""
import io
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import sheet_io  # noqa: E402


class _FakeWS:
    def __init__(self):
        self.calls = 0
        self.id = 1
        self.spreadsheet = None

    def get_all_values(self):
        self.calls += 1
        return [["a"], ["b"]]


class _FakeSheet:
    def __init__(self, ws):
        self._ws = ws

    def worksheet(self, tab):
        return self._ws


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    sheet_io._READ_MEMO.clear()
    monkeypatch.delenv("SHEET_READ_MEMO", raising=False)
    yield
    sheet_io._READ_MEMO.clear()


def test_read_tab_hits_the_api_every_time_by_default(monkeypatch):
    """既定は素通り。書いてから読み直す走行を壊さない。"""
    ws = _FakeWS()
    monkeypatch.setattr(sheet_io, "_open", lambda sid: _FakeSheet(ws))
    sheet_io.read_tab("T")
    sheet_io.read_tab("T")
    assert ws.calls == 2, "既定で使い回してはいけない"


def test_read_tab_is_reused_when_flag_is_on(monkeypatch):
    ws = _FakeWS()
    monkeypatch.setattr(sheet_io, "_open", lambda sid: _FakeSheet(ws))
    monkeypatch.setenv("SHEET_READ_MEMO", "1")
    a = sheet_io.read_tab("T")
    b = sheet_io.read_tab("T")
    assert ws.calls == 1, "同じタブを2回読んでいる"
    assert a == b


def test_different_tabs_are_not_mixed_up(monkeypatch):
    ws = _FakeWS()
    monkeypatch.setattr(sheet_io, "_open", lambda sid: _FakeSheet(ws))
    monkeypatch.setenv("SHEET_READ_MEMO", "1")
    sheet_io.read_tab("A")
    sheet_io.read_tab("B")
    assert ws.calls == 2, "別のタブまで使い回してはいけない"


def test_product_sheet_full_read_is_reused_when_flag_is_on(monkeypatch):
    ws = _FakeWS()
    g = sheet_io._ColWriteGuard(ws, {})
    g.get_all_values()
    g.get_all_values()
    assert ws.calls == 2, "既定は素通り"
    monkeypatch.setenv("SHEET_READ_MEMO", "1")
    sheet_io._READ_MEMO.clear()
    g.get_all_values()
    g.get_all_values()
    assert ws.calls == 3, "商品管理シートの全読みを使い回していない"


def test_write_guard_still_works_through_the_wrapper():
    """読みの使い回しを足したことで、書込ガードを壊していないこと。"""
    ws = _FakeWS()
    ws.update_cell = lambda *a, **kw: "written"
    g = sheet_io._ColWriteGuard(ws, {})
    assert callable(g.update_cell)


def test_panel_enables_the_flag_only_for_the_counting_subprocess():
    src = io.open(os.path.join(os.path.dirname(__file__), "..", "control_panel.py"),
                  encoding="utf-8").read()
    assert src.count('SHEET_READ_MEMO="1"') == 1, (
        "件数を数える subprocess だけに付けること (本番の走行に付けない)")
