"""Regression: 2026-07-24 — RESTOCK writeback は N直書き禁止・AN(override)に書く。

事故: restock_reactivate_master が HIGH の N列(=live ARRAYFORMULA)に仕入コストを直書き →
      spill を塞いで N1=#REF! → 全行 N 崩壊 → psa_to_csv が F(古い価格)を拾い過大 pricing。
根治: cost は N でなく AN列(PRODUCT_COL_COST_OVERRIDE=39)へ。N1 式が AN 優先で読む。
純関数化できない I/O だが、_product_ws を差し替えて batch_update の range を検証する。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "iMakHQ" / "tools"))

import sheet_io


class _FakeWS:
    def __init__(self):
        self.reqs = None

    def batch_update(self, reqs, value_input_option=None):
        self.reqs = reqs


def test_restock_cost_goes_to_AN_not_N(monkeypatch):
    fake = _FakeWS()
    monkeypatch.setattr(sheet_io, "_product_ws", lambda: fake)
    n = sheet_io.restock_reactivate_master(
        itemid_to_row={"111": 227},
        itemid_to_url={"111": "https://jp.mercari.com/item/mXXX"},
        itemid_to_cost={"111": 29999},
    )
    assert n == 1
    ranges = {r["range"]: r["values"][0][0] for r in fake.reqs}
    # cost は AN227 に入る(N227 では絶対ない)
    assert int(ranges.get("AN227")) == 29999
    assert not any(rg.startswith("N") for rg in ranges), f"N列に書いてはいけない: {ranges}"
    # A(供給URL)と D(売切クリア)は従来どおり
    assert "A227" in ranges and ranges["A227"].startswith("https://")
    assert ranges.get("D227") == ""


def test_override_col_is_AN():
    assert sheet_io.PRODUCT_COL_COST_OVERRIDE == 39  # AN (0-indexed 39)


def test_no_cost_skips_override_write(monkeypatch):
    fake = _FakeWS()
    monkeypatch.setattr(sheet_io, "_product_ws", lambda: fake)
    sheet_io.restock_reactivate_master(
        itemid_to_row={"111": 227},
        itemid_to_url={"111": "https://x"},
        itemid_to_cost={"111": ""},   # cost 無し
    )
    ranges = {r["range"] for r in fake.reqs}
    assert "AN227" not in ranges     # cost 無ければ override 書かない
    assert "A227" in ranges and "D227" in ranges
