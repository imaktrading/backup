"""restock_reactivate_master が cost を M列(seed)に書き AN列(凍結)に書かないことの回帰テスト (2026-07-26)。

★真因: RESTOCK writeback が cost を AN(仕入override=N式で最優先=固定)に書いていたため、2026-07-26 に
完成した M=min(生きてる最安) 動的追随を上書き(実測 AN凍結 4→14 に増殖)。→ AN でなく M(現在価格=regular列)を
seed し、N=(M or F)−K + 監視くん M-min で動的追随させる。AN凍結への逆戻りを防ぐ。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import sheet_io


class _FakeWS:
    def __init__(self):
        self.reqs = None

    def batch_update(self, reqs, value_input_option="RAW"):
        self.reqs = reqs


def test_reactivate_seeds_M_not_AN(monkeypatch):
    fake = _FakeWS()
    monkeypatch.setattr(sheet_io, "_product_ws", lambda: fake)
    n = sheet_io.restock_reactivate_master(
        {"358x": 100}, {"358x": "https://sup/1"}, {"358x": "18000"})
    assert n == 1
    ranges = [r["range"] for r in fake.reqs]
    # cost は M列に seed(A/D も更新)。AN列(仕入override=凍結)には**書かない**。
    assert "M100" in ranges, "cost は M列に seed する(動的追随の起点)"
    assert "A100" in ranges and "D100" in ranges
    an_col = ("A" + chr(65 + sheet_io.PRODUCT_COL_COST_OVERRIDE - 26))  # 39→AN
    assert not any(r.startswith(an_col) and r != "A100" for r in ranges), "AN列(凍結)には書かない"
    # M に入る値は cost の数字のみ
    m_val = next(r["values"][0][0] for r in fake.reqs if r["range"] == "M100")
    assert m_val == "18000"


def test_reactivate_no_cost_skips_M(monkeypatch):
    fake = _FakeWS()
    monkeypatch.setattr(sheet_io, "_product_ws", lambda: fake)
    sheet_io.restock_reactivate_master({"358y": 5}, {"358y": "https://sup/2"}, {})
    ranges = [r["range"] for r in fake.reqs]
    assert "A5" in ranges and "D5" in ranges and "M5" not in ranges  # cost無=M seed しない
