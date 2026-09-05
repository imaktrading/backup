# -*- coding: utf-8 -*-
"""商材の箱は「補URL を1行 / 再仕入れ を次の行」に分ける (2026-09-06 ユーザー指示).

## なぜ
箱の中を 4列に流し込んでいたので、PSA は

    補① 補② 補③ 再①
    再② 再③

と折り返し、**補URL の隣に 再仕入れ①** が並んでいた。工程の切れ目が読めず、
「今どっちの作業をしているか」が見た目から分からない。

もう1つ、並べ替えの `_step_rank` は `"在庫切れ再仕入れ"` という語で
再仕入れを見分けていたが、実ラベルは `🛒 PSA 再仕入れ ①` で **一度も一致していなかった**
(全部「その他」扱い)。ラベルを変えた時に並びが黙って壊れる形だったので、
ここは描画結果そのものを見て守る。
"""
from __future__ import annotations

import io
import os

import pytest

_HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = io.open(os.path.join(_HQ, "control_panel.py"), encoding="utf-8").read()

# 期待する並び: {箱: [[1行目のラベル片], [2行目のラベル片]]}
EXPECT = {
    "PSA (TCG)":   [["PSA 補URL ①", "PSA 補URL ②", "PSA 補URL ③"],
                    ["PSA 再仕入れ ①", "PSA 再仕入れ ②", "PSA 再仕入れ ③"]],
    "Tシャツ (UT)": [["UT 補URL ②", "UT 補URL ③"],
                    ["UT 再仕入れ ①", "UT 再仕入れ ②", "UT 再仕入れ ③"]],
    "一番くじ":     [["くじ 補URL ②", "くじ 補URL ③"],
                    ["くじ 再仕入れ ①", "くじ 再仕入れ ②"]],
}


def test_step_rank_matches_the_real_label():
    """並べ替えの語が実ラベルと合っていること (合わないと黙って混ざる)。"""
    assert '"在庫切れ再仕入れ" in lab' not in _SRC, \
        "実ラベルは「再仕入れ」。この語では一度も一致しない"
    assert '1 if "再仕入れ" in lab else 2' in _SRC


def _boxes():
    """既存メンテを実際に描画して、商材の箱の (row, col, label) を返す。"""
    tk = pytest.importorskip("tkinter")
    import sys
    sys.path.insert(0, _HQ)
    import control_panel as cp

    try:
        root = tk.Tk()
    except tk.TclError:                       # 画面の無い環境
        pytest.skip("no display")
    root.withdraw()
    top = tk.Toplevel(root)
    cp.ListingPanel(top, mode="maint")
    root.update_idletasks()

    out: dict[str, list[tuple[int, int, str]]] = {}

    def walk(w):
        for c in w.winfo_children():
            try:
                text = str(c.cget("text"))
            except Exception:                 # noqa: BLE001  text を持たない widget
                text = ""
            if "出品した後の作業" in text:
                cells = []
                for parent in c.winfo_children():
                    for b in [parent] + list(parent.winfo_children()):
                        if b.winfo_class() == "Button":
                            g = b.grid_info()
                            cells.append((int(g["row"]), int(g["column"]),
                                          str(b.cget("text"))))
                name = text.split("📦 ")[1].split(" —")[0]
                out[name] = sorted(cells)
            walk(c)

    try:
        walk(top)
    finally:
        root.destroy()
    return out


@pytest.mark.parametrize("box_name", list(EXPECT))
def test_each_step_gets_its_own_row(box_name):
    boxes = _boxes()
    assert box_name in boxes, f"{box_name} の箱が描かれていない"
    rows: dict[int, list[str]] = {}
    for r, _c, label in boxes[box_name]:
        rows.setdefault(r, []).append(label)

    want = EXPECT[box_name]
    assert len(rows) == len(want), f"{box_name}: 行数が違う {rows}"
    for r, want_row in enumerate(want):
        got = rows[r]
        assert len(got) == len(want_row), f"{box_name} row{r}: {got}"
        for label, frag in zip(got, want_row):
            assert frag in label, f"{box_name} row{r}: {label} に {frag} が無い"


def test_columns_line_up_across_boxes():
    """3つの箱でボタン幅と ①②③ の列位置が揃うこと (ncol=3 固定)。"""
    assert "_grid_named(box, [], ncol=3, groups=_groups)" in _SRC
