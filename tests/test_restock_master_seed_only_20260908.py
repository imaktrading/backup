# -*- coding: utf-8 -*-
"""RESTOCK の書き戻しが、直した仕入値を古い値で潰していた (2026-09-08)。

`restock_reactivate_master` のコメントは「M列を **seed**」だが、実装は毎回 **上書き**。
「RESTOCK確定」タブの `最安¥` は確定した時点の値なので、走行のたびに古い値が戻る。

実害: 補URLが別カードだった出品 820049712142 を実測で ¥57,747 に直したのに、
      その後の走行で **¥15,000** (今どの仕入元にも無い値) に戻っていた。
      その値で cost-plus が回ると、また安く出品される。
"""
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "iMakHQ", "tools")))

import sheet_io   # noqa: E402


class _WS:
    """M列の現在値を返し、batch_update を記録するだけの偽シート。"""

    def __init__(self, m_by_row):
        self.m_by_row = m_by_row
        self.sent = []

    def get(self, rng):
        lo = int(rng.split(":")[0][1:])
        hi = int(rng.split(":")[1][1:])
        return [[self.m_by_row.get(r, "")] for r in range(lo, hi + 1)]

    def batch_update(self, reqs, value_input_option=None):
        self.sent = reqs


def _run(monkeypatch, m_by_row, cost):
    ws = _WS(m_by_row)
    monkeypatch.setattr(sheet_io, "_product_ws", lambda: ws)
    sheet_io.restock_reactivate_master({"111": 10}, {"111": "https://x/1"}, {"111": cost})
    return ws.sent


def _ranges(sent):
    return [r["range"] for r in sent]


def test_seeds_when_the_cost_cell_is_empty(monkeypatch):
    sent = _run(monkeypatch, {10: ""}, "20000")
    assert "M10" in _ranges(sent)


def test_does_not_overwrite_an_existing_cost(monkeypatch):
    """人が直した値・監視くんが入れた最安を、古い確定値で潰さない (今回の事故)。"""
    sent = _run(monkeypatch, {10: "57747"}, "15000")
    assert "M10" not in _ranges(sent)
    assert "A10" in _ranges(sent) and "D10" in _ranges(sent)   # A/D は今までどおり


def test_url_and_soldout_are_always_synced(monkeypatch):
    """供給URLと売り切れ解除は毎回そろえる (在庫監視が取り下げ直すのを防ぐ本来の目的)。"""
    sent = _run(monkeypatch, {10: "57747"}, "15000")
    assert {"A10", "D10"} <= set(_ranges(sent))


def test_no_cost_no_write(monkeypatch):
    sent = _run(monkeypatch, {10: ""}, "")
    assert "M10" not in _ranges(sent)
