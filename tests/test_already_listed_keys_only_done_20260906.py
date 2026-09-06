# -*- coding: utf-8 -*-
"""「同じカードが既に出品中」の判定が自分自身を見ていた (2026-09-06)。

`already_listed_keys()` は 用途=出品 の行の KEY を集めるが、**転記済かどうかを見ていなかった**。
まだ足していない行の KEY まで入るので、足そうとしている行が自分自身とぶつかり
**100% 弾かれる**。実測 (2026-09-06): 未転記16件のうち 16件が自己衝突、
本当に出品中だったものは 0件。人が証明番号を16件打ち込んで **追加0件**、
印も付かないので翌日また同じ16件が並んでいた。
"""
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "iMakHQ", "tools")))

import newcand_confirm as nc   # noqa: E402


def _row(use, key, done=""):
    r = [""] * len(nc.OUT_HEADER)
    r[0] = use
    r[nc.OUT_DONE_COL] = done
    r[nc.OUT_URL_COL] = "https://jp.mercari.com/item/m%s" % key.replace(":", "")
    r[nc.OUT_KEY_COL] = key
    return r


def test_pending_row_does_not_block_itself(monkeypatch):
    """未転記の行は「埋まっている」に数えない (自己衝突の再発ガード)。"""
    rows = [list(nc.OUT_HEADER),
            _row(nc.USE_LIST, "one_piece_tcg:OP01-001"),            # 未転記 = これから足す
            _row(nc.USE_LIST, "pokemon_tcg:SV8a-220", nc.DONE_MARK_HIGH)]  # 転記済
    monkeypatch.setattr(nc, "_read_tab", lambda tab: rows)
    keys = nc.already_listed_keys()
    assert "pokemon_tcg:SV8a-220" in keys
    assert "one_piece_tcg:OP01-001" not in keys


def test_sold_rows_also_count_as_settled(monkeypatch):
    """売り切れ印も結論済なので数える (印のある行は再び足さない)。"""
    rows = [list(nc.OUT_HEADER),
            _row(nc.USE_LIST, "one_piece_tcg:OP01-001", nc.DONE_MARK_SOLD)]
    monkeypatch.setattr(nc, "_read_tab", lambda tab: rows)
    assert nc.already_listed_keys() == {"one_piece_tcg:OP01-001"}


def test_aux_rows_are_not_counted(monkeypatch):
    """用途=補URL は出品枠を埋めない (2枚目の仕入元にすぎない)。"""
    rows = [list(nc.OUT_HEADER),
            _row(nc.USE_AUX, "one_piece_tcg:OP01-001", nc.DONE_MARK_HIGH)]
    monkeypatch.setattr(nc, "_read_tab", lambda tab: rows)
    assert nc.already_listed_keys() == set()
