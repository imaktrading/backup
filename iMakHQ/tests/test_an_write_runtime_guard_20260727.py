# -*- coding: utf-8 -*-
"""★AN列(仕入override)への書込を **実行時に** 拒否できることの回帰テスト (2026-07-27)。

## なぜ source 走査の test では足りなかったか (監査指摘 2026-07-27)
先に入れた `test_no_an_column_write_20260727.py` は `f"AN{row}"` 等の **文字列リテラル4形**しか
見ておらず、以下で簡単に迂回できた:
  - `ws.update_cell(row, 40, v)`      … 数値の列指定 (AN = 1-indexed 40)
  - `chr(65 + idx0)` で列文字を動的生成 … **このリポジトリの確立済みスタイル**
    (write_aux_urls / write_keys が実際にこの書き方をしている)
= 「構造的に封じた」は過大表現だった。そこで **書込の出口(worksheet)** で列指定の方法に依らず弾く。

## 守る不変条件
商品管理シートの AN 列には **プログラムからは一切書けない**。AN が入ると N=(M or F)−K の
動的追随が止まり仕入値が凍結 → 供給が値上がりしても据置 → 気づかないまま安売り
(実測: Boa Hancock P-066 が ¥29,999 凍結のまま実勢 ¥48,000 に対し $353.98 で出品)。
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import sheet_io  # noqa: E402

AN0 = sheet_io.PRODUCT_COL_COST_OVERRIDE          # 39 (0-indexed)
AN1 = AN0 + 1                                      # 40 (gspread の 1-indexed)


class _FakeWS:
    """書込を記録するだけのダミー worksheet。"""

    def __init__(self):
        self.calls = []

    def batch_update(self, reqs, value_input_option="RAW"):
        self.calls.append(("batch_update", reqs))

    def update(self, rng, values, value_input_option="RAW"):
        self.calls.append(("update", rng))

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
    return sheet_io._ANWriteGuard(_FakeWS())


# ------------------------------------------------ A1 レンジ解釈(純関数)
@pytest.mark.parametrize("rng,expected", [
    ("AN5", True),            # 単セル
    ("AN2:AN9", True),        # AN だけの範囲
    ("A2:AN9", True),         # ★A〜AN を一括更新 = AN を巻き込む
    ("AM1:AO1", True),        # AN をまたぐ
    ("A:AN", True),           # 列全体
    ("M100", False),          # 正しい書き方(M seed)
    ("A2:AG9", False),        # 補URL帯(AC-AG)は無関係
    ("シート1!AN3", True),     # シート名付き
    ("2:5", True),            # 行だけ = 全列を含む → 安全側で拒否
])
def test_range_touches_an_column(rng, expected):
    assert sheet_io.range_touches_col(rng, AN0) is expected


def test_col_letters_to_idx0():
    assert sheet_io._col_letters_to_idx0("A") == 0
    assert sheet_io._col_letters_to_idx0("AN") == AN0 == 39
    assert sheet_io._col_letters_to_idx0("M") == 12


# ------------------------------------------------ 実行時に弾く(4経路)
def test_batch_update_to_an_is_denied():
    g = _guarded()
    with pytest.raises(PermissionError, match="AN列"):
        g.batch_update([{"range": "AN100", "values": [["29999"]]}])


def test_update_cell_by_numeric_col_is_denied():
    """★source走査では検知できなかった迂回1: 数値の列指定。"""
    g = _guarded()
    with pytest.raises(PermissionError, match="AN列"):
        g.update_cell(100, AN1, "29999")


def test_chr_generated_column_letter_is_denied():
    """★迂回2: chr() で列文字を組み立てる(このリポジトリの確立済みスタイル)。"""
    col = "A" + chr(65 + AN0 - 26)          # → 'AN'
    assert col == "AN"
    g = _guarded()
    with pytest.raises(PermissionError, match="AN列"):
        g.update(f"{col}100", [["29999"]])


def test_update_cells_to_an_is_denied():
    g = _guarded()
    with pytest.raises(PermissionError, match="AN列"):
        g.update_cells([_Cell(100, AN1)])


def test_wide_range_covering_an_is_denied():
    """A〜AN の一括更新で AN を巻き込むケースも止める。"""
    g = _guarded()
    with pytest.raises(PermissionError, match="AN列"):
        g.batch_update([{"range": "A2:AN2", "values": [[""] * 40]}])


# ------------------------------------------------ 正常な書込は素通り
def test_normal_writes_pass_through():
    ws = _FakeWS()
    g = sheet_io._ANWriteGuard(ws)
    g.batch_update([{"range": "M100", "values": [["18000"]]},
                    {"range": "AC5:AG5", "values": [[""] * 5]}])
    g.update_cell(3, 13, "x")                 # M列(1-indexed 13)
    assert [c[0] for c in ws.calls] == ["batch_update", "update_cell"]


def test_reads_pass_through():
    g = _guarded()
    assert g.get_all_values() == [["h"], ["v"]]


# ------------------------------------------------ 本番経路が壊れていない
def test_restock_reactivate_master_still_works_under_guard(monkeypatch):
    """M seed(正しい書き方)はガード下でも通ること = 既存機能を壊していない。"""
    ws = _FakeWS()
    monkeypatch.setattr(sheet_io, "_product_ws", lambda: sheet_io._ANWriteGuard(ws))
    n = sheet_io.restock_reactivate_master({"358x": 100}, {"358x": "https://s/1"}, {"358x": "18000"})
    assert n == 1
    ranges = [r["range"] for r in ws.calls[0][1]]
    assert "M100" in ranges and not any(r.startswith("AN") for r in ranges)


def test_write_keys_still_works_under_guard(monkeypatch):
    """KEY(AI列)書込もガードに掛からないこと(AI は AN の手前)。"""
    ws = _FakeWS()
    monkeypatch.setattr(sheet_io, "_product_ws", lambda: sheet_io._ANWriteGuard(ws))
    n = sheet_io.write_keys({"iid": 50}, {"iid": "RP-028"})
    assert n == 1
    assert ws.calls[0][1][0]["range"] == "AI50"
