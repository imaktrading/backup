# -*- coding: utf-8 -*-
"""商品管理シートの読み取りも 429 (1分あたりの上限) なら待って読み直す (2026-09-15)。

実害: パネルを開き直した直後に 🛒 PSA 再仕入れ ② CSV を押すと product_index() が
APIError 429 (Read requests per minute per user) で落ちた。read_tab には待ち直しがあったが、
商品管理シートの読み取り (_ColWriteGuard.get_all_values / 29か所) は素通りだった。
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import sheet_io  # noqa: E402


class _FakeWs:
    def __init__(self, errors):
        self.errors = list(errors)
        self.calls = 0

    def get_all_values(self):
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return [["h"], ["v"]]


def _quota():
    return Exception("APIError: [429]: Quota exceeded for quota metric 'Read requests'")


def test_waits_and_retries_on_quota(monkeypatch):
    slept = []
    monkeypatch.setattr(sheet_io._t, "sleep", lambda s: slept.append(s))
    monkeypatch.delenv("SHEET_READ_MEMO", raising=False)
    ws = _FakeWs([_quota(), _quota()])
    assert sheet_io._ColWriteGuard(ws).get_all_values() == [["h"], ["v"]]
    assert ws.calls == 3 and slept == [20, 40]


def test_other_errors_are_not_swallowed(monkeypatch):
    monkeypatch.setattr(sheet_io._t, "sleep", lambda s: None)
    ws = _FakeWs([ValueError("broken")])
    with pytest.raises(ValueError):
        sheet_io._ColWriteGuard(ws).get_all_values()
    assert ws.calls == 1


def test_gives_up_after_retries(monkeypatch):
    monkeypatch.setattr(sheet_io._t, "sleep", lambda s: None)
    ws = _FakeWs([_quota()] * 5)
    with pytest.raises(Exception):
        sheet_io._ColWriteGuard(ws).get_all_values()
    assert ws.calls == 4
