# -*- coding: utf-8 -*-
"""商品管理シートへの行追加が N列(数式) / AN列 を踏まないこと (2026-09-09 実害)。

N は `=ARRAYFORMULA((M or F)−K)` の spill 出力で、1セルでも塞ぐと N1=#REF! になり
**全行の仕入値が空**になる。2026-09-09 に実際に起きた:

    N1 = #REF! (Array result was not expanded because it would overwrite data in N2754.)
    → 出品中 721行 / 未出品 1,714行 とも N は全部 空

原因は `ws.append_rows([[""] * 40])` (= A..AN を書く)。N/AN のガードは 2026-08-02 に
入っていたが、見ていたのが update 系5メソッドだけで **append は素通り**だった
(2026-08-02 ichibankuji_restock 事故と同型の再発)。

★ユーザー指摘「価格とかスプシに入れなくてもいいの?」も同じ経路。M列(仕入値の種)を
  書いていなかったので、未出品1,714行のうち515行が M 空だった。
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "tools"))
import sheet_io as S            # noqa: E402
import newcand_confirm as N     # noqa: E402


class _FakeWS:
    def __init__(self):
        self.appended, self.batches = [], []

    def append_row(self, row, value_input_option=None):
        return self.append_rows([row], value_input_option)

    def append_rows(self, rows, value_input_option=None):
        self.appended.append(rows)
        w = max(len(r) for r in rows)
        end = chr(ord("A") + w - 1)
        return {"updates": {"updatedRange": f"商品管理シート!A2760:{end}{2759 + len(rows)}"}}

    def batch_update(self, reqs, value_input_option=None):
        self.batches.append(reqs)


def test_appendは守る列に届く長さなら弾かれる():
    """列を指定しない append は **行の長さ**でどこまで書くかが決まる。"""
    g = S._ColWriteGuard(_FakeWS(), S._PRODUCT_GUARDED_COLS)
    with pytest.raises(PermissionError, match="N列"):
        g.append_rows([[""] * 40])                 # A..AN = N も AN も踏む
    with pytest.raises(PermissionError, match="N列"):
        g.append_row([""] * 14)                    # ちょうど N まで届く
    g.append_rows([[""] * 13])                     # A..M = 安全 (例外にならない)


def test_ヘルパはAからMをappendしOからAMを別レンジで書く(monkeypatch):
    ws = _FakeWS()
    monkeypatch.setattr(S, "_product_ws", lambda: ws)
    row = [""] * 40
    row[0], row[2], row[12], row[17], row[28] = "https://u", "タイトル", "5000", "TCG", "https://aux"
    assert S.append_product_rows([row]) == 1
    # append したのは A..M だけ (13列)
    assert len(ws.appended[0][0]) == S.PRODUCT_COL_COST == 13
    assert ws.appended[0][0][12] == "5000"                 # M列 = 仕入値の種は載る
    # 残りは O..AM の別レンジ = N も AN も触らない
    rng = ws.batches[0][0]["range"]
    assert rng.startswith("O") and rng.split(":")[1].startswith("AM")
    tail = ws.batches[0][0]["values"][0]
    assert tail[17 - 14] == "TCG" and tail[28 - 14] == "https://aux"
    assert len(tail) == S.PRODUCT_COL_COST_OVERRIDE - S.PRODUCT_COL_COST - 1   # AN を含まない


def test_種から出品行はM列に仕入値を書く():
    """候補タブが持っている価格を出品行へ写す (書かないと N=(M or F)−K が空のまま)。"""
    items = [{"i": 0, "url": "https://jp.mercari.com/item/m1", "title": "PSA10 テスト",
              "key": "one_piece_tcg:OP01-001", "pid": "", "price": "7800"}]
    rows, marked, skipped = N.plan_high_rows(items, {0: "12345678"})
    assert len(rows) == 1 and not skipped
    assert rows[0][N.HIGH_PRICE_COL] == "7800"
    assert rows[0][S.PRODUCT_COL_COST] == ""          # N は空のまま (数式が作る)


def test_価格が無い候補はM列を空のままにする():
    items = [{"i": 0, "url": "https://jp.mercari.com/item/m2", "title": "PSA10 テスト2",
              "key": "", "pid": "", "price": None}]
    rows, _, _ = N.plan_high_rows(items, {0: "87654321"})
    assert rows[0][N.HIGH_PRICE_COL] == ""
