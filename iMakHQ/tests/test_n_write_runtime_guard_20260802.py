# -*- coding: utf-8 -*-
"""★N列(仕入価格 SSOT・ARRAYFORMULA spill)への書込を **実行時に** 拒否できることの回帰テスト (2026-08-02)。

## 経緯 (同型事故 3 回目)
1. 2026-07-24: `restock_reactivate_master` が N列に直書き → N の ARRAYFORMULA が spill 破損
   → N1=#REF! → 全1415行の N が空 → 古い F 由来で価格が過大 (DON!! $279.98)。対策 A: M seed へ切替。
2. 2026-07-26〜27: RESTOCK が AN に書くようになり凍結。対策 B: `_ANWriteGuard` (AN 実行時拒否)。
3. **2026-08-02 (本件)**: `ichibankuji_restock.build_restock_reqs` が **N列に直書き** して
   同型再発 (N109-N123 の 7 行を焼き、他 1400行 が #REF! で offer_calc の cost=0 表示 →
   赤字承諾リスク)。対策 C: 本 test が守るガード。N列を AN と同じ実行時拒否対象に追加。

## 守る不変条件
商品管理シートの N 列には **プログラムからは一切書けない**。N は ARRAYFORMULA (M or F)−K の
spill 出力で、1セル書込むと spill が塞がり全 1415行が #REF! になる。cost を反映したいなら
M 列(regular)を seed する運用に統一。
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import sheet_io  # noqa: E402

N0 = sheet_io.PRODUCT_COL_COST                     # 13 (0-indexed) = N列
N1 = N0 + 1                                         # 14 (gspread の 1-indexed)


class _FakeWS:
    """書込を記録するだけのダミー worksheet。"""

    def __init__(self):
        self.calls = []

    def batch_update(self, reqs, value_input_option="RAW"):
        self.calls.append(("batch_update", reqs))

    def update(self, rng, values, value_input_option="RAW"):
        self.calls.append(("update", rng))

    def update_acell(self, rng, value):
        self.calls.append(("update_acell", rng))

    def update_cell(self, row, col, value):
        self.calls.append(("update_cell", row, col))

    def update_cells(self, cells, value_input_option="RAW"):
        self.calls.append(("update_cells", cells))

    def get_all_values(self):
        return [["h"], ["v"]]


class _Cell:
    def __init__(self, row, col):
        self.row, self.col = row, col


def _guarded():
    """本番 _product_ws と同じ AN+N 複合ガードを付けた fake ws。"""
    return sheet_io._ColWriteGuard(_FakeWS(), sheet_io._PRODUCT_GUARDED_COLS)


# ------------------------------------------------ A1 レンジ解釈(純関数)
@pytest.mark.parametrize("rng,expected", [
    ("N5", True),             # 単セル
    ("N2:N999", True),        # N だけの範囲
    ("A2:N9", True),          # ★A〜N を一括更新 = N を巻き込む
    ("M100:O100", True),      # N をまたぐ
    ("N:N", True),            # 列全体
    ("M100", False),          # 正しい書き方(M seed)
    ("A2:M9", False),         # M までなら N は無関係
    ("シート1!N3", True),      # シート名付き
    ("2:5", True),            # 行だけ = 全列を含む → 安全側で拒否
])
def test_range_touches_n_column(rng, expected):
    assert sheet_io.range_touches_col(rng, N0) is expected


# ------------------------------------------------ 実行時に弾く(5 write メソッド × N)
def test_batch_update_to_n_is_denied():
    """★本件の元凶: ichibankuji_restock が {'range': 'N{row}', ...} を送っていた同型。"""
    g = _guarded()
    with pytest.raises(PermissionError, match=r"N列"):
        g.batch_update([{"range": "N100", "values": [["12200"]]}])


def test_update_to_n_is_denied():
    g = _guarded()
    with pytest.raises(PermissionError, match=r"N列"):
        g.update("N100", [["12200"]])


def test_update_acell_to_n_is_denied():
    g = _guarded()
    with pytest.raises(PermissionError, match=r"N列"):
        g.update_acell("N100", "12200")


def test_update_cell_by_numeric_col_is_denied():
    """★source走査では検知できない迂回: 数値の列指定。"""
    g = _guarded()
    with pytest.raises(PermissionError, match=r"N列"):
        g.update_cell(100, N1, "12200")


def test_update_cells_to_n_is_denied():
    g = _guarded()
    with pytest.raises(PermissionError, match=r"N列"):
        g.update_cells([_Cell(100, N1)])


def test_wide_range_covering_n_is_denied():
    """A〜N の一括更新で N を巻き込むケースも止める。"""
    g = _guarded()
    with pytest.raises(PermissionError, match=r"N列"):
        g.batch_update([{"range": "A2:N2", "values": [[""] * 14]}])


# ------------------------------------------------ AN列ガードは維持されている
def test_an_write_still_denied_under_composite_guard():
    """★退行検知: 複合ガード化しても AN 拒否が生きていること。"""
    g = _guarded()
    with pytest.raises(PermissionError, match=r"AN列"):
        g.batch_update([{"range": "AN100", "values": [["29999"]]}])


# ------------------------------------------------ 正常な書込は素通り
def test_m_seed_pass_through():
    """M列 seed (2026-07-27 以降の正しい書き方) はガード下でも通ること。"""
    ws = _FakeWS()
    g = sheet_io._ColWriteGuard(ws, sheet_io._PRODUCT_GUARDED_COLS)
    g.batch_update([{"range": "M100", "values": [["18000"]]},
                    {"range": "AC5:AG5", "values": [[""] * 5]}])
    g.update_cell(3, 13, "x")                     # M列(1-indexed 13)
    assert [c[0] for c in ws.calls] == ["batch_update", "update_cell"]


def test_reads_pass_through():
    g = _guarded()
    assert g.get_all_values() == [["h"], ["v"]]


# ------------------------------------------------ ichibankuji_restock が M seed になっている
def test_ichibankuji_restock_seeds_m_not_n(monkeypatch):
    """★本命: ichibankuji_restock.build_restock_reqs が M列 seed になっていて、
    ガード下で通ること = 本件の対策が入っていること。"""
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
    import ichibankuji_restock as ir  # noqa: E402
    reqs = ir.build_restock_reqs({100: {"a": "https://s/", "b": "358x", "cost": "12200"}})
    ranges = [r["range"] for r in reqs]
    assert any(r == "M100" for r in ranges), f"M列 seed が無い: {ranges}"
    assert not any(r.startswith("N") and not r.startswith("N/") for r in ranges), \
        f"N列に書いている(同型再発): {ranges}"
    # ガードを通しても PermissionError にならないこと
    ws = _FakeWS()
    g = sheet_io._ColWriteGuard(ws, sheet_io._PRODUCT_GUARDED_COLS)
    g.batch_update(reqs)  # ここで raise しなければ OK


def test_ichibankuji_restock_no_cost_skips_m_write():
    """cost 無し行は M を書かない (誤って既存 cost を消さない)。"""
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
    import ichibankuji_restock as ir  # noqa: E402
    reqs = ir.build_restock_reqs({100: {"a": "https://s/", "b": "358x"}})     # cost 無し
    ranges = [r["range"] for r in reqs]
    assert not any(r.startswith("M") for r in ranges), f"cost 無しなのに M を書いた: {ranges}"


def test_ichibankuji_restock_live_thin_writes_nothing():
    """live_thin (まだ生きている出品) は A/B/D/M を触らない (itemID を剥がさない)。"""
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
    import ichibankuji_restock as ir  # noqa: E402
    reqs = ir.build_restock_reqs({100: {"kind": "live_thin", "a": "x", "b": "y", "cost": "1000"}})
    assert reqs == [], f"live_thin なのに書いた: {reqs}"
