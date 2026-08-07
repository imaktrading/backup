"""Regression: 2026-07-24 N直書き禁止 → 2026-07-26 改訂 cost は M(seed)へ(AN凍結もしない)。

事故(07-24): restock_reactivate_master が HIGH の N列(=live ARRAYFORMULA)に仕入コストを直書き →
      spill を塞いで N1=#REF! → 全行 N 崩壊 → psa_to_csv が F(古い価格)を拾い過大 pricing。
07-24 対策: cost を AN列(override)へ。→ ★07-26 再改訂: AN(N式で最優先=固定)は M=min 動的追随を
      上書きするため NG(実測 AN凍結 4→14 増殖)。cost は M列(現在価格=regular列)に seed し、
      N=(M or F)−K + 監視くん M-min で動的追随。N直書き禁止は不変・AN 不可触。
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
    # ★2026-07-26 改訂: cost は M227(現在価格 seed)に入る。N直書き禁止(#REF!事故)は不変、
    # かつ AN(凍結)にも書かない(M-min 動的追随を上書きしないため)。
    assert int(ranges.get("M227")) == 29999                     # cost は M列に seed
    assert not any(rg.startswith("N") for rg in ranges), f"N直書き禁止(#REF!事故): {ranges}"
    assert "AN227" not in ranges, f"AN(凍結)に書かない=M-min動的追随を守る: {ranges}"
    # A(供給URL)と D(売切クリア)は従来どおり
    assert "A227" in ranges and ranges["A227"].startswith("https://")
    assert ranges.get("D227") == ""


def test_override_col_is_AN():
    assert sheet_io.PRODUCT_COL_COST_OVERRIDE == 39  # AN (0-indexed 39・定数は残す=手動override用)


def test_no_cost_skips_M_seed(monkeypatch):
    fake = _FakeWS()
    monkeypatch.setattr(sheet_io, "_product_ws", lambda: fake)
    sheet_io.restock_reactivate_master(
        itemid_to_row={"111": 227},
        itemid_to_url={"111": "https://x"},
        itemid_to_cost={"111": ""},   # cost 無し
    )
    ranges = {r["range"] for r in fake.reqs}
    assert "M227" not in ranges      # cost 無ければ M seed しない
    assert "A227" in ranges and "D227" in ranges
