# -*- coding: utf-8 -*-
"""1点ものの仕入元が HIGH に在れば、行を足さない (2026-09-21)。

再出品用の行が、出品中の行と同じスニダン/メルカリの URL で作られ、1つの現物に
eBay 出品が2つ付く所だった (監視くん指摘)。HIGH に行を足す口は append_product_rows 1本。
"""
import os
import sys

sys.path.insert(0, os.path.join(r"C:\dev\iMak\iMakHQ", "tools"))

import sheet_io as S  # noqa: E402

M1 = "https://jp.mercari.com/item/m111"
SN = "https://snkrdunk.com/apparels/335125/used/49652029"
UQ = "https://www.uniqlo.com/jp/ja/products/E123"


def _row(url, aux=()):
    r = [""] * 39
    r[0] = url
    for i, u in enumerate(aux):
        r[S.PRODUCT_COL_AUX_START + i] = u
    return r


def test_1点ものの見分け():
    assert S.is_one_of_a_kind(M1) and S.is_one_of_a_kind(SN)
    assert not S.is_one_of_a_kind(UQ)          # 公式サイトは何度でも買える


def test_A列か補URLに在れば外す():
    claimed = S.claimed_supply_urls([["URL"], _row("https://jp.mercari.com/item/m9", aux=[SN])])
    keep, dropped = S.drop_claimed_supply([_row(SN), _row(M1)], claimed)
    assert [r[0] for r in keep] == [M1]
    assert dropped == [(SN, "HIGH に同じ仕入元が在る")]


def test_同時に足す行どうしも1行():
    keep, dropped = S.drop_claimed_supply([_row(M1), _row(M1)], set())
    assert len(keep) == 1 and dropped[0][1] == "同時に足す行と重複"


def test_公式サイトは重複でも外さない():
    keep, _ = S.drop_claimed_supply([_row(UQ), _row(UQ)], {UQ})
    assert len(keep) == 2


def test_append_は押さえ済みの仕入元を書かない(monkeypatch):
    class _WS:
        def __init__(self):
            self.appended = []

        def get_all_values(self):
            return [["URL"], _row(SN)]

        def append_rows(self, rows, value_input_option=None):
            self.appended.extend(rows)
            return {"updates": {"updatedRange": "商品管理シート!A10:M10"}}

        def batch_update(self, *a, **k):
            pass

    ws = _WS()
    monkeypatch.setattr(S, "_product_ws", lambda: ws)
    assert S.append_product_rows([_row(SN), _row(M1)]) == 1
    assert [r[0] for r in ws.appended] == [M1]
